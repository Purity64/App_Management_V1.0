import eel
import json
import os
import subprocess
import sys
import base64
import shutil
import uuid
import tkinter as tk 
from tkinter import filedialog
from io import BytesIO
import bottle # จำเป็นต้องมีบรรทัดนี้ เพื่อทำ Server ส่งไฟล์รูป/วิดีโอ

# --- IMPORT ICON LIBS ---
# ต้องติดตั้ง: pip install pywin32 pillow bottle eel
try:
    import win32ui, win32gui, win32con, win32api
    from PIL import Image
    HAS_ICON_LIB = True
except ImportError:
    HAS_ICON_LIB = False
    print("Warning: Icon libraries not found. Please run 'pip install pywin32 pillow'")

# --- 1. RESOURCE PATH (แก้ปัญหา Path ผิดตอนเป็น EXE) ---
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller/Nuitka """
    base_path = os.path.dirname(os.path.abspath(__file__))
    if hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    return os.path.join(base_path, relative_path)

# เริ่มต้น Eel
web_path = resource_path('web')
eel.init(web_path)

# --- 2. APPDATA SETUP (เตรียมที่เก็บไฟล์) ---
# สร้างโฟลเดอร์เก็บข้อมูลใน AppData ของผู้ใช้ (เขียนไฟล์ได้แน่นอน 100%)
APP_DATA_DIR = os.path.join(os.getenv('LOCALAPPDATA'), 'AppManagementV1')
if not os.path.exists(APP_DATA_DIR):
    os.makedirs(APP_DATA_DIR)

# สร้างโฟลเดอร์สำหรับเก็บรูป/วิดีโอพื้นหลัง
BG_DATA_DIR = os.path.join(APP_DATA_DIR, "backgrounds")
if not os.path.exists(BG_DATA_DIR):
    os.makedirs(BG_DATA_DIR)

LAUNCHER_DATA_FILE = os.path.join(APP_DATA_DIR, "launcher_data.json")
BROWSER_DATA_FILE = os.path.join(APP_DATA_DIR, "url_groups_glass.json")

# --- 3. SERVER ROUTE (หัวใจสำคัญของระบบใหม่) ---
# สร้างเส้นทางพิเศษ ให้หน้าเว็บดึงไฟล์จาก AppData ได้
# เช่น: <img src="/user_media/my_pic.jpg">
@bottle.route('/user_media/<path:path>')
def static_media(path):
    return bottle.static_file(path, root=BG_DATA_DIR)

# --- 4. ฟังก์ชันเลือกพื้นหลัง (แบบ Copy ไฟล์) ---
@eel.expose
def select_and_copy_bg(file_type):
    # ซ่อนหน้าต่างหลัก Tkinter
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    
    # กำหนดประเภทไฟล์
    filetypes = [("Video Files", "*.mp4;*.webm")] if file_type == 'video' else [("Image Files", "*.jpg;*.png;*.jpeg;*.gif;*.webp")]
    
    # เปิดหน้าต่างเลือกไฟล์
    file_path = filedialog.askopenfilename(title=f"Select {file_type}", filetypes=filetypes)
    
    if file_path:
        try:
            # 1. เอาชื่อไฟล์เดิมมาใช้
            filename = os.path.basename(file_path)
            
            # (Optional) ถ้าต้องการป้องกันชื่อซ้ำ ให้เปิดบรรทัดล่างนี้แทน
            # filename = f"{uuid.uuid4().hex[:8]}_{filename}" 

            # 2. กำหนดปลายทางใน AppData
            dest_path = os.path.join(BG_DATA_DIR, filename)
            
            # 3. Copy ไฟล์ไปที่ AppData (ทับไฟล์เดิมถ้าชื่อเหมือนกัน)
            shutil.copy(file_path, dest_path)
            
            # 4. ส่ง URL สั้นๆ กลับไปให้หน้าเว็บ
            # ผลลัพธ์จะเป็น: /user_media/ชื่อไฟล์.นามสกุล
            return f"/user_media/{filename}"

        except Exception as e:
            print(f"Background Error: {e}")
            return None
    return None

# --- 5. ฟังก์ชันดึงไอคอน (แบบ Base64) ---
# ใช้ Base64 สำหรับไอคอนเหมือนเดิม เพราะไฟล์เล็กและจัดการง่ายกว่า
def get_icon_base64(exe_path):
    if not HAS_ICON_LIB or not os.path.exists(exe_path): return None 
    try:
        large, small = win32gui.ExtractIconEx(exe_path, 0)
        hicon = large[0] if large else small[0] if small else None
        if not hicon: return None

        hdc = win32ui.CreateDCFromHandle(win32gui.GetDC(0))
        hbmp = win32ui.CreateBitmap()
        hbmp.CreateCompatibleBitmap(hdc, 32, 32)
        hdc = hdc.CreateCompatibleDC()
        hdc.SelectObject(hbmp)
        hdc.DrawIcon((0,0), hicon)
        
        bmpinfo = hbmp.GetInfo()
        bmpstr = hbmp.GetBitmapBits(True)
        img = Image.frombuffer('RGBA', (bmpinfo['bmWidth'], bmpinfo['bmHeight']), bmpstr, 'raw', 'BGRA', 0, 1)
        
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode('utf-8')
        
        win32gui.DestroyIcon(hicon)
        win32gui.DeleteObject(hbmp.GetHandle())
        return f"data:image/png;base64,{img_str}"
    except Exception as e:
        print(f"Icon Extract Error: {e}")
        return None

@eel.expose
def extract_exe_icon(path):
    p = path.replace('"', '').strip()
    return get_icon_base64(p)

# --- 6. API ทั่วไป (Save/Load/Launch) ---

@eel.expose
def load_data():
    default_data = { "globalBg": "", "globalBgType": "", "tags": [], "apps": {}, "browsers": [] }
    if os.path.exists(LAUNCHER_DATA_FILE):
        try:
            with open(LAUNCHER_DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "browsers" not in data: data["browsers"] = []
                return data
        except: return default_data
    return default_data

@eel.expose
def save_data(data):
    try:
        with open(LAUNCHER_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Save Error: {e}")
        return False

@eel.expose
def launch_app(path):
    if not path: return
    try:
        p = path.replace('"', '').strip()
        if sys.platform == 'win32':
            os.startfile(p)
        else:
            subprocess.Popen(['xdg-open', p])
    except Exception as e:
        print(f"Launch Error: {e}")

@eel.expose
def browse_exe_path():
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    file_path = filedialog.askopenfilename(title="Select Application (.exe)", filetypes=[("Executable Files", "*.exe"), ("All Files", "*.*")])
    if file_path: return file_path.replace("\\", "/") 
    return ""

# --- BROWSER GROUP FUNCTIONS ---

@eel.expose
def get_saved_groups():
    if os.path.exists(BROWSER_DATA_FILE):
        with open(BROWSER_DATA_FILE, "r", encoding="utf-8") as f: return json.load(f)
    return {}

@eel.expose
def save_group(name, data):
    groups = get_saved_groups()
    groups[name] = data
    with open(BROWSER_DATA_FILE, "w", encoding="utf-8") as f: json.dump(groups, f, ensure_ascii=False, indent=4)

@eel.expose
def delete_group(name):
    groups = get_saved_groups()
    if name in groups: del groups[name]
    with open(BROWSER_DATA_FILE, "w", encoding="utf-8") as f: json.dump(groups, f, ensure_ascii=False, indent=4)

@eel.expose
def launch_group_urls(exe_path, profile, urls, startup_apps=[]):
    # Launch Extra Apps first
    if startup_apps:
        for app_path in startup_apps:
            if app_path:
                try:
                    p = app_path.replace('"', '').strip()
                    if sys.platform == 'win32': os.startfile(p)
                    else: subprocess.Popen(['xdg-open', p])
                except Exception as e: print(f"Error launching extra app {app_path}: {e}")

    # Launch Browser
    if not exe_path or not os.path.exists(exe_path): return
    cmd = [exe_path]
    exe_name = os.path.basename(exe_path).lower()
    is_chromium = "chrome.exe" in exe_name or "brave.exe" in exe_name or "msedge.exe" in exe_name or "opera" in exe_name
    
    if is_chromium and profile and profile != "Default":
        cmd.append(f'--profile-directory={profile}')
    
    cmd.extend(urls)
    subprocess.Popen(cmd, close_fds=True)

@eel.expose
def get_profiles_from_path(exe_path):
    profiles = {"Default": "Default"}
    if not exe_path: return profiles

    local_app = os.getenv('LOCALAPPDATA')
    exe_lower = exe_path.lower()
    user_data = None

    if "chrome.exe" in exe_lower:
        user_data = os.path.join(local_app, r"Google\Chrome\User Data")
    elif "brave.exe" in exe_lower:
        user_data = os.path.join(local_app, r"BraveSoftware\Brave-Browser\User Data")
    elif "msedge.exe" in exe_lower:
        user_data = os.path.join(local_app, r"Microsoft\Edge\User Data")
    
    if user_data and os.path.exists(os.path.join(user_data, "Local State")):
        try:
            with open(os.path.join(user_data, "Local State"), "r", encoding="utf-8") as f:
                data = json.load(f)
            info_cache = data.get("profile", {}).get("info_cache", {})
            for folder_name, info in info_cache.items():
                display_name = info.get("name", folder_name)
                profiles[display_name] = folder_name
        except Exception as e:
            print(f"Profile Read Error: {e}")
            
    return profiles

# เริ่มต้น Eel
eel.start('index.html', size=(1200, 800), port=0)