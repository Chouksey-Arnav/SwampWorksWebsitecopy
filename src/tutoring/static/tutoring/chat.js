/* Booking chat. Works as plain form posts without this file; this adds
   live updates (polling), optimistic sending and retry.
   Message text is only ever written with textContent, never innerHTML. */
(function () {
    'use strict';

    var thread = document.getElementById('thread');
    if (!thread) return;

    var composer = document.getElementById('composer');
    var box = document.getElementById('body');
    var note = document.getElementById('composer-note');
    var jump = document.getElementById('jump');
    var pollUrl = thread.dataset.pollUrl;
    var sendUrl = thread.dataset.sendUrl;
    var lastId = parseInt(thread.dataset.lastId, 10) || 0;
    var status = thread.dataset.status;
    var token = composer ? composer.querySelector('[name="csrfmiddlewaretoken"]').value : '';
    var draftKey = 'chat-draft:' + sendUrl;

    var sending = false;
    var timer = null;
    var failures = 0;
    var quietSince = Date.now();
    var stopped = false;

    // ---- Scrolling ---------------------------------------------------------
    function nearBottom() { return thread.scrollHeight - thread.scrollTop - thread.clientHeight < 90; }
    function toBottom(smooth) { thread.scrollTo({ top: thread.scrollHeight, behavior: smooth ? 'smooth' : 'auto' }); }
    thread.addEventListener('scroll', function () { if (nearBottom() && jump) jump.hidden = true; });
    if (jump) jump.addEventListener('click', function () { toBottom(true); jump.hidden = true; box && box.focus(); });
    toBottom(false);

    // ---- Rendering ---------------------------------------------------------
    var currentDay = (function () {
        var days = thread.querySelectorAll('.day');
        return days.length ? days[days.length - 1].dataset.day : null;
    })();

    function bubble(text, time, removed) {
        var b = document.createElement('div');
        b.className = 'bubble';
        if (removed) {
            var em = document.createElement('em');
            em.textContent = 'Message removed by an officer';
            b.appendChild(em);
        } else {
            var span = document.createElement('span');
            span.className = 'text';
            span.textContent = text;
            b.appendChild(span);
        }
        var t = document.createElement('time');
        t.textContent = time;
        b.appendChild(t);
        return b;
    }

    function hideEmpty() {
        var empty = document.getElementById('thread-empty');
        if (empty) empty.remove();
    }

    function addDay(m, before) {
        if (m.day_key === currentDay) return;
        var d = document.createElement('div');
        d.className = 'day';
        d.dataset.day = m.day_key;
        var s = document.createElement('span');
        s.textContent = m.day_label;
        d.appendChild(s);
        if (before) { thread.insertBefore(d, before); } else { thread.appendChild(d); }
        currentDay = m.day_key;
    }

    function exists(id) { return !!thread.querySelector('.msg[data-id="' + id + '"]'); }

    function insert(m) {
        hideEmpty();
        var el = document.createElement('div');
        el.className = 'msg ' + (m.mine ? 'mine' : 'theirs') + (m.removed ? ' removed' : '');
        el.dataset.id = m.id;
        el.appendChild(bubble(m.body, m.time, m.removed));
        // Normally append. If a lower id shows up late (rare race), keep order.
        var later = null;
        thread.querySelectorAll('.msg[data-id]').forEach(function (other) {
            if (!later && parseInt(other.dataset.id, 10) > m.id) later = other;
        });
        if (later) { thread.insertBefore(el, later); } else { addDay(m); thread.appendChild(el); }
        return el;
    }

    function applyRemoved(ids) {
        ids.forEach(function (id) {
            var el = thread.querySelector('.msg[data-id="' + id + '"]');
            if (el && !el.classList.contains('removed')) {
                var time = el.querySelector('time').textContent;
                el.classList.add('removed');
                el.replaceChild(bubble('', time, true), el.querySelector('.bubble'));
            }
        });
    }

    function closeComposer(text) {
        if (composer) composer.remove();
        if (note) note.remove();
        composer = box = note = null;
        if (!document.getElementById('chat-closed')) {
            var p = document.createElement('p');
            p.id = 'chat-closed';
            p.className = 'chat-closed';
            p.textContent = text;
            thread.parentNode.appendChild(p);
        }
    }

    // ---- Polling -----------------------------------------------------------
    function interval() {
        var quiet = Date.now() - quietSince;
        if (quiet > 180000) return 15000;
        if (quiet > 60000) return 8000;
        return 4000;
    }

    function schedule(delay) {
        clearTimeout(timer);
        if (stopped) return;
        timer = setTimeout(poll, delay == null ? interval() : delay);
    }

    function poll() {
        if (stopped) return;
        if (document.hidden || sending) { schedule(); return; }
        fetch(pollUrl + '?after=' + lastId, {
            credentials: 'same-origin', cache: 'no-store', headers: { 'X-Requested-With': 'fetch' }
        }).then(function (r) {
            if (r.redirected || r.status === 401 || r.status === 403 || r.status === 404) {
                stopped = true;
                setNote('You have been signed out of this chat. Reload the page to continue.', true);
                throw new Error('stopped');
            }
            return r.json();
        }).then(function (data) {
            failures = 0;
            setNote('');
            var stick = nearBottom();
            var fresh = false, fromOther = false;
            data.messages.forEach(function (m) {
                if (m.id > lastId) lastId = m.id;
                if (exists(m.id)) return;
                insert(m);
                fresh = true;
                if (!m.mine) fromOther = true;
            });
            if (data.removed && data.removed.length) applyRemoved(data.removed);
            if (fresh) {
                quietSince = Date.now();
                if (stick) { toBottom(true); } else if (fromOther && jump) { jump.hidden = false; }
            }
            if (data.status !== status) {
                if (data.status === 'open') { location.reload(); return; }
                status = data.status;
                closeComposer(data.status_text);
            }
        }).catch(function (err) {
            if (err && err.message === 'stopped') return;
            failures += 1;
            if (failures >= 3) setNote('Connection lost. Retrying…', true);
        }).then(function () {
            schedule(failures ? Math.min(30000, 4000 * (failures + 1)) : null);
        });
    }

    function setNote(text, isError) {
        if (!note) return;
        note.textContent = text;
        note.classList.toggle('is-error', !!isError);
    }

    document.addEventListener('visibilitychange', function () { if (!document.hidden) { quietSince = Date.now(); schedule(0); } });
    window.addEventListener('online', function () { schedule(0); });

    // ---- Sending -----------------------------------------------------------
    function autosize() {
        if (!box) return;
        box.style.height = 'auto';
        box.style.height = Math.min(box.scrollHeight, 150) + 'px';
    }

    function saveDraft() {
        try { box.value ? sessionStorage.setItem(draftKey, box.value) : sessionStorage.removeItem(draftKey); } catch (e) { /* private mode */ }
    }

    function pendingBubble(text) {
        hideEmpty();
        var el = document.createElement('div');
        el.className = 'msg mine pending';
        el.appendChild(bubble(text, 'Sending…', false));
        thread.appendChild(el);
        toBottom(false);
        return el;
    }

    function fail(el, text, message) {
        el.classList.remove('pending');
        el.classList.add('failed');
        el.querySelector('time').textContent = 'Not sent';
        var tools = document.createElement('div');
        tools.className = 'msg-fail';
        var why = document.createElement('span');
        why.textContent = message;
        var retry = document.createElement('button');
        retry.type = 'button';
        retry.textContent = 'Retry';
        retry.addEventListener('click', function () { tools.remove(); el.classList.remove('failed'); el.classList.add('pending'); el.querySelector('time').textContent = 'Sending…'; deliver(el, text); });
        var drop = document.createElement('button');
        drop.type = 'button';
        drop.textContent = 'Remove';
        drop.addEventListener('click', function () { el.remove(); });
        tools.appendChild(why); tools.appendChild(retry); tools.appendChild(drop);
        el.appendChild(tools);
    }

    function deliver(el, text) {
        sending = true;
        var data = new FormData();
        data.append('body', text);
        data.append('csrfmiddlewaretoken', token);
        fetch(sendUrl, { method: 'POST', body: data, credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch' } })
            .then(function (r) {
                if (r.redirected) { throw new Error('signed-out'); }
                return r.json().then(function (j) { return { ok: r.ok && j.ok, j: j }; });
            })
            .then(function (res) {
                if (!res.ok) { fail(el, text, (res.j && res.j.error) || 'Could not send.'); return; }
                var m = res.j.message;
                if (exists(m.id)) { el.remove(); return; }
                el.classList.remove('pending');
                el.dataset.id = m.id;
                el.querySelector('time').textContent = m.time;
                addDay(m, el);
                quietSince = Date.now();
                // lastId is deliberately NOT advanced here: the next poll may carry an
                // earlier message from the other person, and we must not skip it.
            })
            .catch(function (err) {
                fail(el, text, err && err.message === 'signed-out' ? 'You are signed out. Reload the page.' : 'No connection.');
            })
            .then(function () { sending = false; schedule(1200); });
    }

    function submit() {
        var text = box.value.replace(/\s+$/, '');
        if (!text.trim()) return;
        if (text.length > 1000) { setNote('That message is ' + text.length + ' characters. The limit is 1000.', true); return; }
        setNote('');
        var el = pendingBubble(text);
        box.value = '';
        saveDraft();
        autosize();
        deliver(el, text);
    }

    if (composer && box) {
        try { var draft = sessionStorage.getItem(draftKey); if (draft) { box.value = draft; autosize(); } } catch (e) { /* ignore */ }
        composer.addEventListener('submit', function (event) { event.preventDefault(); submit(); });
        box.addEventListener('input', function () { autosize(); saveDraft(); });
        box.addEventListener('keydown', function (event) {
            if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); submit(); }
        });
        document.querySelectorAll('[data-starter]').forEach(function (button) {
            button.addEventListener('click', function () {
                box.value = button.dataset.starter;
                autosize(); box.focus();
                box.setSelectionRange(box.value.length, box.value.length);
            });
        });
        if (matchMedia('(pointer: fine)').matches) box.focus();
    }

    if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', function () { if (nearBottom()) toBottom(false); });
    }

    schedule();
})();
