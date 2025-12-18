import cv2
import mediapipe as mp
import json
import time
from collections import deque
import paramiko
from scp import SCPClient

# --- CẤU HÌNH KẾT NỐI ROBOT ---
ROBOT_IP = "192.168.31.234"

ROBOT_PORT = 2000             # Cổng SSH mặc định

ROBOT_USER = "pi"
ROBOT_PASSWORD = "1"        # Password của user pi
ROBOT_DEST_PATH = "/home/pi/jupyter/command.json" # Đường dẫn đích trên Robot

# --- CẤU HÌNH HỆ THỐNG ---
CMD_FILE = "command.json"   # Tên file tạm trên máy tính
WAVE_LEN = 15
WAVE_THRESH = 25
SEND_COOLDOWN = 2.5         # Thời gian nghỉ giữa các lần gửi lệnh
ROBOT_STREAM_URL = 'http://192.168.31.234:8000/stream.mjpg'

# --- DANH SÁCH LỆNH ---
GESTURE_MAP = {
    "RESET":       {"name":"reset", "direction":""},
    "WAVE_LEFT":   {"name":"wave_servo", "direction":"left"},
    "WAVE_RIGHT":  {"name":"wave_servo", "direction":"right"},
    "WAVE_BOTH":   {"name":"wave_servo", "direction":"both"},
}

# --- KHỞI TẠO MEDIAPIPE ---
mp_pose = mp.solutions.pose
mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils
mp_styles = mp.solutions.drawing_styles

pose = mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)
hands = mp_hands.Hands(max_num_hands=2, min_detection_confidence=0.7, min_tracking_confidence=0.5)

# --- KẾT NỐI CAMERA ---
print(f"Connecting camera: {ROBOT_STREAM_URL}")
cap = cv2.VideoCapture(ROBOT_STREAM_URL)
if not cap.isOpened(): 
    print("Cannot connect to robot stream, using local webcam...")
    cap = cv2.VideoCapture(0)

history_left  = deque(maxlen=WAVE_LEN)
history_right = deque(maxlen=WAVE_LEN)
last_time_sent = 0

# =====================================================
# HÀM CHUYỂN FILE QUA SSH (PARAMIKO)
# =====================================================
def transfer_file_ssh(local_path, remote_path):
    """
    Gửi file từ máy tính sang Raspberry Pi qua giao thức SCP
    """
    try:
        # 1. Tạo kết nối SSH
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ROBOT_IP, port=ROBOT_PORT, username=ROBOT_USER, password=ROBOT_PASSWORD, timeout=2.0)
        
        # 2. Mở kênh SCP và gửi file
        with SCPClient(ssh.get_transport()) as scp:
            scp.put(local_path, remote_path)
        
        print(f"✅ [SCP SUCCESS] Uploaded to {ROBOT_IP}:{remote_path}")
        
        # 3. Đóng kết nối
        ssh.close()
        return True
    except Exception as e:
        print(f"❌ [SCP ERROR] Could not transfer file: {e}")
        return False

# =====================================================
# GHI FILE JSON VÀ GỌI HÀM GỬI
# =====================================================
def write_cmd(key):
    global last_time_sent
    now = time.time()

    # Logic Cooldown: RESET được ưu tiên gửi ngay, WAVE phải chờ
    if key != "RESET" and now - last_time_sent < SEND_COOLDOWN:
        return

    if key not in GESTURE_MAP:
        return

    data = GESTURE_MAP[key]
    data["timestamp_sent"] = now

    # 1. Ghi file JSON cục bộ trên máy tính
    try:
        with open(CMD_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except IOError as e:
        print(f"Lỗi ghi file cục bộ: {e}")
        return

    print(f"SENDING >>> {key}: {data}")
    
    # 2. Gửi file sang Robot
    transfer_file_ssh(CMD_FILE, ROBOT_DEST_PATH)
    
    last_time_sent = now

# =====================================================
# CHECK LIKE (RESET)
# =====================================================
def check_like(hand):
    thumb_tip = hand.landmark[4]
    thumb_ip  = hand.landmark[3]
    idx_tip   = hand.landmark[8]
    idx_mcp   = hand.landmark[5]
    mid_tip   = hand.landmark[12]
    mid_mcp   = hand.landmark[9]

    is_thumb_up = thumb_tip.y < thumb_ip.y
    is_idx_fold = idx_tip.y > idx_mcp.y
    is_mid_fold = mid_tip.y > mid_mcp.y

    return is_thumb_up and is_idx_fold and is_mid_fold

# =====================================================
# VÒNG LẶP CHÍNH
# =====================================================
print("Hệ thống bắt đầu. Nhấn 'q' để thoát.")

while True:
    ok, frame = cap.read()
    if not ok:
        print("Mất tín hiệu camera.")
        break

    # Lật ảnh gương
    frame = cv2.flip(frame, 1)
    h, w, _ = frame.shape

    img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    
    # Process MediaPipe
    pose_result = pose.process(img)
    hand_result = hands.process(img)

    gesture = None
    debug_text = "Waiting..."
    text_color = (200, 200, 200)

    # 1. VẼ POSE
    if pose_result.pose_landmarks:
        mp_drawing.draw_landmarks(
            frame, pose_result.pose_landmarks, mp_pose.POSE_CONNECTIONS,
            landmark_drawing_spec=mp_styles.get_default_pose_landmarks_style()
        )

    # 2. CHECK LIKE (RESET)
    if hand_result.multi_hand_landmarks:
        for hnd in hand_result.multi_hand_landmarks:
            mp_drawing.draw_landmarks(frame, hnd, mp_hands.HAND_CONNECTIONS)
            if check_like(hnd):
                gesture = "RESET"
                break

    # 3. CHECK WAVE (VẪY TAY)
    energy_L = energy_R = 0
    
    if not gesture and pose_result.pose_landmarks:
        lm = pose_result.pose_landmarks.landmark
        def P(id): return int(lm[id].x * w), int(lm[id].y * h)

        le = P(mp_pose.PoseLandmark.LEFT_ELBOW)
        re = P(mp_pose.PoseLandmark.RIGHT_ELBOW)
        lw = P(mp_pose.PoseLandmark.LEFT_WRIST)
        rw = P(mp_pose.PoseLandmark.RIGHT_WRIST)
        li = P(mp_pose.PoseLandmark.LEFT_INDEX)
        ri = P(mp_pose.PoseLandmark.RIGHT_INDEX)

        # Tính toán năng lượng Wave
        if lw[1] < le[1]: # Tay trái giơ lên
            history_left.append(li[0])
            if len(history_left) == WAVE_LEN:
                energy_L = max(history_left) - min(history_left)
        else:
            history_left.clear()

        if rw[1] < re[1]: # Tay phải giơ lên
            history_right.append(ri[0])
            if len(history_right) == WAVE_LEN:
                energy_R = max(history_right) - min(history_right)
        else:
            history_right.clear()

        # Xác định gesture
        if energy_L > WAVE_THRESH and energy_R > WAVE_THRESH:
            gesture = "WAVE_BOTH"
        elif energy_L > WAVE_THRESH:
            gesture = "WAVE_LEFT"
        elif energy_R > WAVE_THRESH:
            gesture = "WAVE_RIGHT"

    # 4. GỬI LỆNH
    if gesture:
        debug_text = gesture
        text_color = (0, 255, 0)
        write_cmd(gesture)
    else:
        if time.time() - last_time_sent < SEND_COOLDOWN:
            debug_text = "Cooldown..."
            text_color = (0, 165, 255)

    # 5. HIỂN THỊ UI
    cv2.rectangle(frame, (0,0), (w, 80), (0,0,0), -1)
    cv2.putText(frame, f"ACTION: {debug_text}", (20, 55),
                cv2.FONT_HERSHEY_SIMPLEX, 1.5, text_color, 3)

    # Thanh năng lượng
    bar_L = min(int(energy_L * 2), 200)
    bar_R = min(int(energy_R * 2), 200)
    
    cv2.rectangle(frame, (20, h-40), (20 + bar_L, h-20), (0,255,0), -1)
    cv2.putText(frame, "L Wave", (20, h-50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)

    cv2.rectangle(frame, (w-220, h-40), (w-220 + bar_R, h-20), (0,255,0), -1)
    cv2.putText(frame, "R Wave", (w-220, h-50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)

    cv2.imshow("Robot Controller (SSH)", frame)
    if cv2.waitKey(1) == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
