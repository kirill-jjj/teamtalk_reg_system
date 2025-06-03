// This file can be used if you prefer to keep JavaScript separate.
// For now, the countdown script is embedded in register_en.html and register_ru.html.

// Example of how it might look if externalized:
/*
function getRussianPlural(number, one, few, many) {
    number = Math.abs(number);
    number %= 100;
    if (number >= 5 && number <= 20) { return many; }
    number %= 10;
    if (number === 1) { return one; }
    if (number >= 2 && number <= 4) { return few; }
    return many;
}

function startCountdown(durationSeconds, displayElementId, lang) {
    let timer = durationSeconds;
    const displayElement = document.getElementById(displayElementId);
    if (!displayElement) {
        console.error("Countdown display element not found:", displayElementId);
        return;
    }

    function updateDisplay() {
        if (timer < 0) {
            displayElement.textContent = (lang === "ru" ? "истекло" : "expired");
            // Optionally, disable download links or show a message
            return;
        }

        const minutes = Math.floor(timer / 60);
        const seconds = timer % 60;

        if (lang === "ru") {
            const paddedSeconds = seconds < 10 && minutes > 0 ? '0' + seconds : seconds;
            if (minutes > 0) {
                 displayElement.textContent = minutes + ":" + paddedSeconds;
            } else {
                displayElement.textContent = seconds + " " + getRussianPlural(seconds, "секунда", "секунды", "секунд");
            }
        } else { // English formatting
            const paddedSeconds = seconds < 10 ? '0' + seconds : seconds;
            displayElement.textContent = minutes + ":" + paddedSeconds;
        }
    }

    updateDisplay(); // Initial call to display time immediately

    const intervalId = setInterval(function () {
        timer--;
        updateDisplay();
        if (timer < 0) {
            clearInterval(intervalId);
        }
    }, 1000);
}

// Ensure this runs after the DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    const countdownElement = document.getElementById('countdown-timer');
    if (countdownElement) {
        const currentLang = document.documentElement.lang || "en";
        const initialSeconds = 10 * 60; // 10 minutes
        startCountdown(initialSeconds, 'countdown-timer', currentLang);
    }
});
*/