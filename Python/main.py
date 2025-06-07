import dash
from dash import dcc
from dash import html
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go
import numpy as np
from bleak import BleakScanner, BleakClient
import asyncio
import threading
import json
import queue
from collections import deque
from scipy.spatial.transform import Rotation as R

# defining Arduino UUID
SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9B"
RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9B"
TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9B"

app = dash.Dash(__name__)

# initialized queue with length of 10
# older values will the thrown away
data_queue = deque(maxlen=10)
queue_lock = threading.Lock()

axis_limit = 50  # axis limit for graphin

curr_rotation = np.eye(3)  # 3x3 identity matrix
curr_time = None  # track time of readings

# app layout
app.layout = html.Div(
    children=[
        dcc.Graph(
            id="live-3d-graph",
            figure=go.Figure(
                data=[
                    go.Scatter3d(
                        x=[0],
                        y=[0],
                        z=[0],
                        mode="lines",
                    )
                ],
                layout=go.Layout(
                    scene=dict(
                        xaxis=dict(range=[-axis_limit, axis_limit]),
                        yaxis=dict(range=[-axis_limit, axis_limit]),
                        zaxis=dict(range=[-axis_limit, axis_limit]),
                    ),
                    title=dict(text="3D live graph"),
                    autosize=False,
                    width=1000,
                    height=1000,
                ),
            ),
        ),
        dcc.Interval(
            id="interval-component", interval=100, n_intervals=0  # in milliseconds
        ),
        html.Button("Start/Stop", id="submit-val", n_clicks=0),
    ]
)


async def run_ble(data_queue: queue.Queue):
    """
    This function start connection to the UNO_R4_UART
    :param data_queue: A queue for holding data from the UNO R4
    """
    while True:
        # finding the UNO R4
        print("Scanning for UNO_R4_UART...")
        device = await BleakScanner.find_device_by_filter(
            lambda d, ad: d.name and "UNO_R4_UART" in d.name
        )
        if not device:
            print("Device not found.")
            await asyncio.sleep(3)
            continue

        try:
            async with BleakClient(device) as client:
                # device connected
                print("Connected to", device.address)

                # on data send to R_X port
                def on_rx(_, data):
                    try:
                        json_data = json.loads(data.decode().strip())
                        new_data = {
                            "a_x": json_data["accel"]["x"],
                            "a_y": json_data["accel"]["y"],
                            "a_z": json_data["accel"]["z"],
                            "g_x": json_data["gyro"]["x"],
                            "g_y": json_data["gyro"]["y"],
                            "g_z": json_data["gyro"]["z"],
                            "time": json_data["time"],
                        }

                        with queue_lock:
                            data_queue.append(new_data)
                    except json.JSONDecodeError:
                        print("Failed to decode JSON")

                await client.start_notify(TX_UUID, on_rx)
                while True:
                    await asyncio.sleep(1)
        except Exception as e:
            print("BLE connection error:", e)

        await asyncio.sleep(3)


def start_ble(data_queue: queue.Queue):
    # start the ble loop
    # equivalent to asyncio.run
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        print("run ble...")
        loop.run_until_complete(run_ble(data_queue))
    except Exception as e:
        print(f"BLE Thread Exception: {e}")


@app.callback(
    Output("live-3d-graph", "figure"),
    Input("interval-component", "n_intervals"),
    State("live-3d-graph", "figure"),
)
def update_graph(n, current_fig):

    new_data = None
    with queue_lock:
        if data_queue:
            new_data = data_queue[-1]  # get the latest data
            data_queue.clear()  # clear all older messages to avoid lag
        else:
            print("No data in deque")
            return dash.no_update

    # calculation
    if new_data:

        # get current graph data
        curr_data = current_fig["data"][0]
        x = list(curr_data["x"])
        y = list(curr_data["y"])
        z = list(curr_data["z"])
        pos = np.array([x[-1], y[-1], z[-1]])  # get the last positiob

        global curr_time, curr_rotation
        curr_vel = np.array([0, 0, 0])  # reset velocity to 0
        if curr_time == None:
            curr_time = new_data["time"]  # this is to match the time of the data sent

        dt = (new_data["time"] - curr_time) / 1000

        curr_time = new_data["time"]  # update time

        omega = np.array(
            [new_data["g_x"], new_data["g_y"], new_data["g_z"]]
        )  # rotation vec
        # round down
        a_x = 0
        a_y = 0
        if abs(0 - new_data["a_x"]) < 0.2:
            a_x = 0
        else:
            a_x = new_data["a_x"]
        if abs(0 - new_data["a_y"]) < 0.7:
            a_y = 0
        else:
            a_y = new_data["a_y"]
        accel = np.array([a_x, a_y, new_data["a_z"] - 9.81])  # acceleration vect
        print(accel)
        d_theta = omega * dt  # new angles
        d_rotation = R.from_rotvec(
            d_theta
        ).as_matrix()  # rotation matrix of those angle

        new_rotation = np.matmul(
            curr_rotation, d_rotation
        )  # this would add up the changes

        # curr_rotation = new_rotation

        new_accel = np.matmul(new_rotation, accel)
        magnitude = np.linalg.norm(new_accel)
        if magnitude >= 1.0:

            curr_vel = curr_vel + new_accel * dt
            new_pos = pos + curr_vel * dt

            new_pos = np.clip(new_pos, -axis_limit, axis_limit)

            # print(
            #    f"new_rotation: {new_rotation}, new_accel: {new_accel}, curr_vel={curr_vel}, pos: {new_pos}"
            # )
            x.append(new_pos[0])
            y.append(new_pos[1])
            z.append(0)
        else:
            return dash.no_update

        fig = go.Figure(
            data=[
                go.Scatter3d(
                    x=x,
                    y=y,
                    z=z,
                    mode="lines",
                )
            ]
        )

        return fig

    else:
        return dash.no_update


# https://stackoverflow.com/questions/63123501/plotly-dash-dcc-interval-disabled-boolean-documentation
@app.callback(
    Output("interval-component", "disabled"),
    [Input("submit-val", "n_clicks")],
    [State("interval-component", "disabled")],
)
def callback_func_start_stop_interval(button_clicks, disabled_state):
    if button_clicks is not None and button_clicks > 0:
        return not disabled_state
    else:
        return disabled_state


if __name__ == "__main__":
    # begin ble as a thread
    ble_thread = threading.Thread(target=start_ble, args=(data_queue,), daemon=True)
    ble_thread.start()
    app.run(debug=False)
