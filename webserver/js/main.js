window.addEventListener('DOMContentLoaded', (event) => {
    let socket = io();

    let state = {
        "enabled": false,
        "brightness": 100
    };
    let enable_switch = document.getElementById("enableSwitch");
    enable_switch.disabled = false;

    let update_controls = () => {
        enable_switch.checked = state.enabled;
        brightness_slider.disabled = !state.enabled;
        brightness_slider.value = state.brightness;
        brightness_value.innerHTML = (state.enabled ? brightness_slider.value : "");
    };

    enable_switch.addEventListener('change', () => {
        state.enabled = enable_switch.checked;
        socket.emit('display_state', state);
        update_controls();
    });

    let brightness_value = document.getElementById("brightnessSpan");
    let brightness_slider = document.getElementById("brightnessSlider");
    brightness_slider.addEventListener('input', () => {
        state.brightness = brightness_slider.value;
        update_controls();
        socket.emit('display_state', state);
    });

    socket.on("display_state", (data) => {
        state = data;
        update_controls();
    });
});
