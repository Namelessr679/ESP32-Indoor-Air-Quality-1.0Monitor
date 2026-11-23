"""Streamlit browser dashboard; the worker owns all sensor and fan IO."""
import streamlit as st

from main import pending_tickets, runtime


def send_command(command):
    try:
        runtime.command(command)
        st.session_state.pop("command_error", None)
    except Exception as exc:
        st.session_state["command_error"] = str(exc)


st.set_page_config(page_title="Air Quality System", page_icon="🌿", layout="wide")
st.title("Air Quality System")
st.caption("Live room readings, CO₂ forecasts, and ventilation control")

with st.sidebar:
    st.subheader("Setup")
    st.write("Set your ESP32 and InfluxDB settings in config.yaml. Restart the server after editing it.")
    missing = pending_tickets()
    if missing:
        st.warning("Automatic prediction is waiting for these modules:")
        for ticket in missing:
            st.write(ticket)
    else:
        st.success("All three HW modules are connected.")
    st.caption("Manual fan controls are available independently of the HW modules.")

controls = st.columns(5)
for column, label, command in zip(
    controls,
    ("Start / Auto", "Stop", "Manual ON", "Manual OFF", "Check ESP32"),
    ("start", "stop", "on", "off", "check"),
):
    column.button(label, key=command, on_click=send_command, args=(command,),
                  use_container_width=True)

if error := st.session_state.get("command_error"):
    st.error(error)

st.info("Closing this browser tab keeps the system running. Press Stop to stop control. "
        "All tabs share the same system.")


@st.fragment(run_every=1)
def live_status():
    state = runtime.snapshot()
    reading = state.get("reading") or {}
    prediction = state.get("prediction") or {}
    status = st.columns(2)
    status[0].metric("Mode", state["mode"])
    status[1].metric("Fan output", state["fan"])
    metrics = st.columns(4)
    metrics[0].metric("Current CO₂", f"{reading['co2']:.0f} ppm" if reading else "—")
    metrics[1].metric("Temperature", f"{reading['temperature']:.1f} °C" if reading else "—")
    metrics[2].metric("Humidity", f"{reading['humidity']:.1f}%" if reading else "—")
    metrics[3].metric("Predicted CO₂", f"{prediction['predicted_co2']:.0f} ppm" if prediction else "—")
    if reading:
        st.caption(f"Last successful pipeline reading: {reading['timestamp']}")
    if prediction:
        st.caption(f"Forecast horizon: {prediction['horizon_minutes']:g} minutes")
    st.subheader("Ventilation recommendation")
    st.write(state.get("recommendation") or "Waiting for a prediction")
    if state["mode"] == "Error":
        st.error(state["message"])
    else:
        st.write(state["message"])
    st.caption("Values show the last successful pipeline cycle. Fan output is an "
               "acknowledged command, not measured fan rotation.")
    with st.expander("System details"):
        st.json(state)


live_status()
