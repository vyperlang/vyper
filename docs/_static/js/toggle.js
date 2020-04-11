document.addEventListener('DOMContentLoaded', function() {

    var checkbox = document.querySelector('input[name=mode]');

    function toggleCssMode(isDay) {
        var mode = (isDay ? "Day" : "Night");
        localStorage.setItem("css-mode", mode);

        var darksheet = $('link[href="_static/css/dark.css"]')[0].sheet;
        darksheet.disabled = isDay;
    }

    if (localStorage.getItem("css-mode") == "Day") {
        toggleCssMode(true);
        checkbox.setAttribute('checked', true);
    }

    checkbox.addEventListener('change', function() {
        document.documentElement.classList.add('transition');
        window.setTimeout(() => {
            document.documentElement.classList.remove('transition');
        }, 1000)
        toggleCssMode(this.checked);
    })

});