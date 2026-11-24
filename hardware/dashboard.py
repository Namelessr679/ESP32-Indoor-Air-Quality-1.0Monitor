"""Streamlit dashboard for sensor readings and fan controls."""
import streamlit as st

from main import read_history, runtime


def send_command(command):
    try:
        runtime.command(command)
        if command == "stop":
            st.session_state["manual_fan"] = False
        st.session_state.pop("command_error", None)
    except Exception as exc:
        st.session_state["command_error"] = str(exc)


def set_manual_fan():
    send_command("on" if st.session_state["manual_fan"] else "off")


st.set_page_config(page_title="Air Quality System", page_icon="🌿", layout="wide")
st.title("Air Quality System")
st.caption("Live sensor readings and ESP32 fan control")

st.subheader("Manual fan")
if "manual_fan" not in st.session_state:
    st.session_state["manual_fan"] = runtime.snapshot()["mode"] == "Manual"
st.toggle("Manual fan", key="manual_fan", on_change=set_manual_fan)
st.markdown(":green[**ON**]" if st.session_state["manual_fan"] else ":red[**OFF**]")

controls = st.columns(2)
for column, label, command in zip(
    controls,
    ("Stop", "Check ESP32"),
    ("stop", "check"),
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
    status = st.columns(2)
    status[0].metric("Mode", state["mode"])
    status[1].metric("Fan output", state["fan"])
    if state["mode"] == "Error":
        st.error(state["message"])
    else:
        st.write(state["message"])
    st.caption("Fan output is an acknowledged command, not measured fan rotation.")
    with st.expander("System details"):
        st.json(state)


live_status()


@st.fragment(run_every=5)
def sensor_chart():
    st.subheader("CO₂ over time")
    try:
        history = read_history()
    except Exception as exc:
        st.warning(f"Could not load sensor readings: {exc}")
        return
    if history.empty:
        st.info("No sensor readings available yet.")
        return
    st.line_chart(history.set_index("time")["co2"])
    latest = history.iloc[-1]
    values = st.columns(3)
    values[0].metric("CO₂", f"{latest.co2:.0f} ppm")
    values[1].metric("Temperature", f"{latest.temp_c:.1f} °C")
    values[2].metric("Humidity", f"{latest.rh:.1f}%")


sensor_chart()
