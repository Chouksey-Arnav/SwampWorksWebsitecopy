/* Site-wide progressive enhancement. Every page works without this file. */
(function () {
    'use strict';

    // Close dropdown menus on outside click or Escape.
    var menus = document.querySelectorAll('details.menu');
    document.addEventListener('click', function (event) {
        menus.forEach(function (menu) {
            if (menu.open && !menu.contains(event.target)) menu.open = false;
        });
    });
    document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape') return;
        menus.forEach(function (menu) {
            if (menu.open) { menu.open = false; menu.querySelector('summary').focus(); }
        });
    });

    // Dismiss flash messages.
    document.querySelectorAll('[data-dismiss]').forEach(function (button) {
        button.addEventListener('click', function () { button.closest('.alert').remove(); });
    });

    // Show / hide password.
    document.querySelectorAll('input[type="password"]').forEach(function (input) {
        var wrap = document.createElement('div');
        wrap.className = 'password-wrap';
        input.parentNode.insertBefore(wrap, input);
        wrap.appendChild(input);
        var toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = 'password-toggle';
        toggle.textContent = 'Show';
        toggle.setAttribute('aria-label', 'Show password');
        toggle.addEventListener('click', function () {
            var show = input.type === 'password';
            input.type = show ? 'text' : 'password';
            toggle.textContent = show ? 'Hide' : 'Show';
            toggle.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
        });
        wrap.appendChild(toggle);
    });

    // Submit a filter form when a control changes (the Search button still works without JS).
    document.querySelectorAll('[data-autosubmit]').forEach(function (control) {
        control.addEventListener('change', function () { control.form.submit(); });
    });

    // Live character counters: <textarea data-counter="#id">.
    document.querySelectorAll('textarea[data-counter]').forEach(function (area) {
        var out = document.querySelector(area.getAttribute('data-counter'));
        if (!out) return;
        var max = parseInt(area.getAttribute('maxlength'), 10);
        var update = function () {
            var left = max - area.value.length;
            out.textContent = left + ' left';
            out.classList.toggle('near', left <= 40);
        };
        area.addEventListener('input', update);
        update();
    });

    // Disable a submit button after the first click so a double-tap can't submit twice.
    document.querySelectorAll('form[data-once]').forEach(function (form) {
        form.addEventListener('submit', function () {
            var button = form.querySelector('[type="submit"]');
            if (button) {
                button.dataset.label = button.innerHTML;
                button.setAttribute('aria-disabled', 'true');
                button.textContent = 'Working…';
            }
        });
    });
    // Back button restores the page from cache with the button still disabled; undo that.
    window.addEventListener('pageshow', function (event) {
        if (!event.persisted) return;
        document.querySelectorAll('form[data-once] [aria-disabled="true"]').forEach(function (button) {
            button.removeAttribute('aria-disabled');
            if (button.dataset.label) button.innerHTML = button.dataset.label;
        });
    });
})();
