import time
import json
import os
from YanAPI import yan_api_init, start_play_motion, set_servos_angles, open_vision_stream, start_voice_tts
import YanAPI

CMD_FILE = "command.json"
last_processed_time = 0
ROBOT_IP = "192.168.31.234"

print("--- ROBOT RECEIVER STARTING ---")
yan_api_init(ROBOT_IP)
open_vision_stream(resolution="640x480")
YanAPI.set_robot_volume_value(90)

print("Watching command file:", os.path.abspath(CMD_FILE))


while True:
    try:
        if os.path.exists(CMD_FILE):
            with open(CMD_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                data = json.loads(content) if content else None

            if not data:
                time.sleep(0.05)
                continue

            timestamp = data.get("timestamp_sent", 0)
            if timestamp <= last_processed_time:
                time.sleep(0.05)
                continue

            name = data.get("name", "")
            direction = data.get("direction", "")

            print("\n>>> COMMAND: {name} ({direction})")


            # -------------------------------------------------------
            # 1. RESET (Motion) - Kích hoạt bằng Like
            # -------------------------------------------------------
            if name == "reset":
                start_play_motion("reset", "", "normal", 1, int(timestamp))
                last_processed_time = timestamp
                continue


            # -------------------------------------------------------
            # 2. WAVE SERVO (Vẫy tay)
            # -------------------------------------------------------
            if name == "wave_servo":

                arms = []
                if direction in ["right", "both"]:
                    arms.append("Right")
                if direction in ["left", "both"]:
                    arms.append("Left")

                # ===== Chuẩn bị giơ vai =====
                prep = {}
                for arm in arms:
                    if arm == "Right":
                        prep["RightShoulderFlex"] = 20       # 20° → giơ lên
                    else:
                        prep["LeftShoulderFlex"] = 160       # MIRROR → 160°
                set_servos_angles(prep, runtime=300)
                time.sleep(0.3)


                # ===== Wave 1 lần =====
                for _ in range(1):
                    start_voice_tts(
                        tts="Hello, my name is Yanshee.",
                        interrupt=False,
                        timestamp=0
                    )

                    flex_in  = {}
                    flex_out = {}

                    for arm in arms:
                        if arm == "Right":
                            flex_in["RightElbowFlex"]  = 20
                            flex_out["RightElbowFlex"] = 100
                        else:
                            flex_in["LeftElbowFlex"]  = 160   # MIRROR
                            flex_out["LeftElbowFlex"] = 80    # MIRROR

                    set_servos_angles(flex_in, runtime=300)
                    time.sleep(0.3)
                    set_servos_angles(flex_out, runtime=300)
                    time.sleep(0.3)


                # ===== Hạ tay =====
                YanAPI.sync_play_motion()


            else:
                # -------------------------------------------------------
                # 3. FALLBACK (Dự phòng)
                # -------------------------------------------------------
                # Các lệnh Head và Raise đã bị bỏ từ phía Camera.
                # Đoạn này chỉ chạy nếu file json bị chỉnh tay thủ công.
                start_play_motion(
                    name=name,
                    direction=direction,
                    speed="normal",
                    repeat=1,
                    timestamp=int(timestamp)
                )

            last_processed_time = timestamp


        time.sleep(0.05)


    except Exception as e:
        print("System error:", e)
        time.sleep(0.5)