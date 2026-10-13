import os
import sys
from pathlib import Path
from . import APP_NAME
FROZEN=bool(getattr(sys,'frozen',False))
ROOT=Path(os.environ['EXAM_ROOM_HOME']).resolve() if os.environ.get('EXAM_ROOM_HOME') else (
    Path.home()/'Documents'/APP_NAME if FROZEN and sys.platform=='darwin' else
    Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent.parent)
UI=(Path(getattr(sys,'_MEIPASS',''))/'exam_room'/'ui') if FROZEN else Path(__file__).parent/'ui'
PUBLIC=(Path(getattr(sys,'_MEIPASS',''))/'exam_room'/'_license_public.json') if FROZEN else Path(__file__).parent/'_license_public.json'

def data_root():
    return Path(os.environ['EXAM_ROOM_HOME']).resolve() if os.environ.get('EXAM_ROOM_HOME') else ROOT

def license_dir():
    if os.environ.get('EXAM_ROOM_HOME'):return data_root()/'license'
    if not FROZEN and os.environ.get('EXAM_ROOM_LICENSE_DIR'): return Path(os.environ['EXAM_ROOM_LICENSE_DIR'])
    if sys.platform=='win32': return Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'ExamRoomTool'
    return Path.home()/'Library'/'Application Support'/'ExamRoomTool' if sys.platform=='darwin' else Path.home()/'.local'/'share'/'ExamRoomTool'
