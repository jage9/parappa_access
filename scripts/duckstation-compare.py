"""Bounded stock DuckStation menu navigation using GDB markers and normal keys."""
import ctypes,json,socket,subprocess,time,sys,datetime,importlib.util,argparse,hashlib,configparser,io,re,threading,contextlib
from pathlib import Path
from duckstation_paths import duckstation_directory
from duckstation_identity import GameIdentityError
root=Path(__file__).resolve().parents[1];folder=duckstation_directory(root)
if not (root/'public-build.json').is_file():sys.path.insert(0,str(root/'developer'))
parser=argparse.ArgumentParser(description='Prepare stock DuckStation Stage 1 for a timing comparison.')
parser.add_argument('--check',action='store_true',help='Verify preparation and exit without playing.')
parser.add_argument('--emulator-dir',type=Path,help='Developer: test an isolated emulator installation.')
parser.add_argument('--smoke-seconds',type=int,default=0,help='Developer: close a normal live session after 1-30 seconds without enabling capture.')
parser.add_argument('--diagnostics',action='store_true',help='Write a bounded text-only support log; no playback audio is recorded.')
parser.add_argument('--benchmark-check',type=int,default=0,metavar='SECONDS',help='Developer: record a bounded passage (1-300 seconds; up to 900 for volatile overwrite, 2400 for campaign).')
parser.add_argument('--mute-cues',action='store_true',help='Detect/log teacher cues without playing them.')
parser.add_argument('--loopback-name',default='ProFX 1-2 (ProFX) [Loopback]')
parser.add_argument('--cue-output',default='ProFX 1-2 (ProFX)',help='Exact WASAPI cue-output device name.')
parser.add_argument('--audio-output',help='Exact playback device name for game, cues and diagnostic loopback together.')
parser.add_argument('--input-check',action='store_true',help='Developer only: three tagged SendInput taps during a bounded check.')
parser.add_argument('--input-latency-check',action='store_true',help='Developer only: 16 tagged window key taps for an input-timing A/B.')
parser.add_argument('--pre-frame-sleep',choices=('off','on'),help='Reversible developer experiment; original setting restored on exit.')
parser.add_argument('--audio-buffer-ms',type=int,choices=(20,25,30),help='Reversible Cubeb buffer experiment; original setting restored on exit.')
parser.add_argument('--developer-play',action='store_true',help='Developer only: replay the verified Stage 1 controller schedule during a bounded check.')
parser.add_argument('--from-title',action='store_true',help='Experimental native title/menu entry instead of preparing Stage 1.')
parser.add_argument('--from-boot',action='store_true',help='Play the opening credits and scenes normally, then continue through native menus.')
parser.add_argument('--auto-start',action='store_true',help='Start without an extra console Enter prompt.')
parser.add_argument('--auto-controller',action='store_true',help='Add standard SDL player-0 controller bindings alongside the keyboard for this session.')
parser.add_argument('--menu-check',action='store_true',help='Developer only: navigate native title/settings during a bounded check.')
parser.add_argument('--pause-check',action='store_true',help='Developer only: exercise Start and D-pad during a bounded Stage 1 check.')
parser.add_argument('--saved-memory-cards',action='store_true',help='Use the existing DuckStation shared memory cards for this run.')
parser.add_argument('--no-speech',action='store_true',help='Use console text instead of screen-reader speech.')
parser.add_argument('--register-check',action='store_true',help='Developer only: validate read-only CPU register discovery against two paused GDB samples.')
parser.add_argument('--card-check',action='store_true',help='Developer only: inspect native Load menu state during a bounded title check.')
parser.add_argument('--card-action',choices=('load','replay','highscores'),default='load',help='Screen exercised by --card-check; never writes a saved game.')
parser.add_argument('--card-screen-capture',action='store_true',help='Developer only: one emulator-rendered card-screen PNG in a fresh logs directory.')
parser.add_argument('--hud-check',action='store_true',help='Developer only: bounded Stage 1 GPU screenshots around the first response handoff.')
parser.add_argument('--handoff-frame-check',action='store_true',help='Developer only: pause at adjacent HUD render passes in two Stage 1 handoffs; not an audio timing benchmark.')
parser.add_argument('--handoff-late-only',action='store_true',help='Developer only: inspect only the longer Stage 1 handoff window.')
parser.add_argument('--handoff-early-only',action='store_true',help='Developer only: inspect only the first Stage 1 handoff window.')
parser.add_argument('--handoff-native-frames',action='store_true',help='Developer only: inspect each native VBlank at the first handoff.')
parser.add_argument('--handoff-stage2-check',action='store_true',help='Developer only: inspect native frames in Stage 2 during a bounded campaign.')
parser.add_argument('--handoff-stage6-check',action='store_true',help='Developer only: play through to Stage 6 and inspect normal and short handoffs.')
parser.add_argument('--handoff-observe',action='store_true',help='Developer only: record native frame-wait snapshots without pausing.')
parser.add_argument('--handoff-sound',action='store_true',help='Enable the verified visual handoff placeholder sound.')
parser.add_argument('--cue-volume',type=int,help='Cue volume percent, 0-200; defaults to the saved launcher setting.')
parser.add_argument('--replay-playback-check',action='store_true',help='Developer only: play one existing replay with no input after selection.')
parser.add_argument('--load-selection-check',action='store_true',help='Developer only: load the first populated DuckStation memory-card slot with no input after selection.')
parser.add_argument('--scene-check',action='store_true',help='Developer only: start a bounded check at the Stage 1 card without skipping it.')
parser.add_argument('--practice-check',action='store_true',help='Developer only: exercise Practice feedback and return through ordinary controller keys.')
parser.add_argument('--no-card-flow-check',action='store_true',help='Developer only: inspect post-win Save flow with both memory-card slots explicitly disabled.')
parser.add_argument('--volatile-card-flow-check',action='store_true',help='Developer only: inspect Save/name using a non-persistent in-memory card, with no backing file.')
parser.add_argument('--volatile-overwrite-check',action='store_true',help='Developer only: reach the overwrite confirmation for the in-memory save without confirming it.')
parser.add_argument('--campaign-check',type=int,default=0,metavar='SECONDS',help='Developer only: bounded six-stage ordinary-input campaign (600-2400 seconds), with cards disabled.')
parser.add_argument('--save-checkpoints',action='store_true',help='Developer campaign: create fresh stage-entry, clear and ending save states.')
parser.add_argument('--checkpoint',type=Path,help='Load a verified DuckStation checkpoint manifest directly, with cues and speech.')
args=parser.parse_args()
if (root/'public-build.json').is_file():
 public_options={'--audio-output','--auto-controller','--cue-volume','--saved-memory-cards',
                 '--handoff-sound','--from-boot','--from-title','--auto-start','--no-speech',
                 '--diagnostics','--check'}
 blocked=sorted({token.split('=',1)[0] for token in sys.argv[1:] if token.startswith('-')
                 and token.split('=',1)[0] not in public_options})
 if blocked:parser.error('Developer-only option unavailable in this release: '+', '.join(blocked))
if args.emulator_dir:folder=args.emulator_dir.resolve()
assert 0<=args.smoke_seconds<=30
if args.cue_volume is None:
 from launcher_settings import load_settings
 args.cue_volume=load_settings()['cue_volume']
if not 0<=args.cue_volume<=200:parser.error('--cue-volume must be between 0 and 200')
checkpoint=None
if args.checkpoint:
 from duckstation_checkpoint_catalog import load_checkpoint
 checkpoint=load_checkpoint(args.checkpoint,root)
 assert not (args.from_title or args.from_boot or args.scene_check),'Checkpoint loading is a separate startup mode'
from launcher_setup import game_image
disc_path=game_image(root)
selected_audio=None
if args.audio_output:
 from audio_devices import resolve_output
 selected_audio=resolve_output(args.audio_output)
 args.cue_output=selected_audio.name
 args.loopback_name=selected_audio.loopback_name
if args.campaign_check:
 assert 600<=args.campaign_check<=2400 and not args.check and not args.benchmark_check and not args.developer_play and not args.from_title and not args.from_boot and not args.saved_memory_cards
 args.benchmark_check=args.campaign_check
if args.from_boot:args.from_title=True
write_diagnostics=bool(args.diagnostics or args.benchmark_check)
assert not args.save_checkpoints or args.campaign_check
assert 0<=args.benchmark_check<=(900 if args.volatile_overwrite_check else 2400 if args.campaign_check else 300)
assert not args.input_check or args.benchmark_check>=30,'Input check requires a bounded check of at least 30 seconds'
assert not args.input_latency_check or args.benchmark_check>=32
assert not args.developer_play or (args.benchmark_check>=145 and not args.input_check and not args.input_latency_check and not args.check and not args.from_title)
assert not args.menu_check or (args.from_title and args.benchmark_check>=40 and not args.developer_play and not args.input_check and not args.input_latency_check)
assert not args.pause_check or (args.benchmark_check>=40 and not args.from_title and not args.developer_play and not args.input_check and not args.input_latency_check)
assert not args.register_check or args.check
assert not args.card_check or (args.from_title and args.benchmark_check>=40 and not args.menu_check)
assert not args.card_screen_capture or ((args.card_check or args.volatile_card_flow_check) and args.benchmark_check>=60)
assert not args.hud_check or (40<=args.benchmark_check<=60 and not args.from_title and not args.developer_play)
assert not args.handoff_frame_check or (args.developer_play and args.benchmark_check>=180 and not args.hud_check)
assert not args.handoff_late_only or args.handoff_frame_check
assert not args.handoff_early_only or (args.handoff_frame_check and not args.handoff_late_only)
assert not args.handoff_native_frames or args.handoff_frame_check
assert not args.handoff_stage2_check or args.campaign_check
assert not args.handoff_stage6_check or (args.campaign_check>=1200 and not args.handoff_stage2_check)
assert not args.replay_playback_check or (args.card_check and args.card_action=='replay' and args.saved_memory_cards and args.benchmark_check>=240 and not args.card_screen_capture)
assert not args.load_selection_check or (args.card_check and args.card_action=='load' and args.saved_memory_cards and args.benchmark_check>=60)
assert not args.scene_check or (args.benchmark_check>=40 and not args.from_title and not args.developer_play)
assert not args.practice_check or (args.from_title and args.benchmark_check>=60 and not args.menu_check and not args.card_check)
assert not args.no_card_flow_check or (args.developer_play and args.benchmark_check>=240 and not args.saved_memory_cards)
assert not args.volatile_card_flow_check or (args.developer_play and args.benchmark_check>=240 and not args.saved_memory_cards and not args.no_card_flow_check)
assert not args.volatile_overwrite_check or (args.volatile_card_flow_check and args.developer_play and args.card_screen_capture and 600<=args.benchmark_check<=900 and not args.campaign_check)
spec=importlib.util.spec_from_file_location('parappa_accessible_menu',root/'scripts/accessible-menu.py')
menu=importlib.util.module_from_spec(spec);spec.loader.exec_module(menu)
speech=menu.Speech(not args.no_speech)
speech.say('Preparing DuckStation '+(f"Stage {checkpoint['stage']} {checkpoint['kind']} checkpoint" if checkpoint else 'from boot' if args.from_boot else 'title screen' if args.from_title else 'Stage 1')+'. Please wait.')
check=subprocess.run(['powershell.exe','-NoProfile','-Command',"@(Get-Process duckstation* -ErrorAction SilentlyContinue).Count"],capture_output=True,text=True,check=True)
assert check.stdout.strip()=='0','Close existing emulators first'
cfg=folder/'settings.ini';original=cfg.read_bytes();p=None;s=None;ram=None;capture=None;monitor=None;cues=None
boot_hint='';boot_hint_stop=threading.Event();boot_hint_thread=None
stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ');out=root/'logs'/('duck-prepare-'+stamp)
u=ctypes.windll.user32
u.GetForegroundWindow.restype=ctypes.c_void_p
u.SetForegroundWindow.argtypes=[ctypes.c_void_p]
u.GetWindowThreadProcessId.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
u.PostMessageW.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t]
def packet(data):
 raw=data.encode();s.sendall(b'$'+raw+b'#'+('%02x'%(sum(raw)%256)).encode())
def response(timeout=30):
 s.settimeout(timeout)
 while True:
  start=s.recv(1)
  if not start:raise RuntimeError('DuckStation closed the debugger connection')
  if start==b'$':break
 data=b''
 while True:
  b=s.recv(1)
  if b==b'#':break
  if not b:raise RuntimeError('GDB disconnected')
  data+=b
 checksum=b''
 while len(checksum)<2:
  part=s.recv(2-len(checksum))
  if not part:raise RuntimeError('Truncated debugger response')
  checksum+=part
 assert int(checksum,16)==sum(data)%256
 s.sendall(b'+');return data.decode()
def command(data):packet(data);return response()
def focus():
 windows=[]
 callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
 @callback
 def enum(hwnd,arg):
  pid=ctypes.c_ulong();u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
  if pid.value==p.pid and u.IsWindowVisible(ctypes.c_void_p(hwnd)):windows.append(hwnd)
  return True
 u.EnumWindows(enum,0);assert windows,'No emulator window'
 return windows[0]
def key(vk):
 hwnd=focus();scan=u.MapVirtualKeyW(vk,0)
 extended=(1<<24) if vk in (0x25,0x26,0x27,0x28) else 0
 # Preparation only: target this emulator window, never global keyboard state.
 assert u.PostMessageW(hwnd,0x100,vk,1|(scan<<16)|extended)
 try:time.sleep(.12)
 finally:assert u.PostMessageW(hwnd,0x101,vk,1|(scan<<16)|extended|(3<<30))
 return True


def watch_boot_hint():
 from duckstation_keyboard import HINT_VK
 held=False
 while not boot_hint_stop.wait(.03):
  foreground=ctypes.c_ulong();u.GetWindowThreadProcessId(u.GetForegroundWindow(),ctypes.byref(foreground))
  down=foreground.value==p.pid and bool(u.GetAsyncKeyState(HINT_VK)&0x8000)
  if down and not held and boot_hint:speech.say(boot_hint)
  held=down

def synthetic_tap(vk):
 # Runtime test only; unlike menu PostMessage, SendInput exercises the OS hook.
 class Keyboard(ctypes.Structure):
  _fields_=[('vk',ctypes.c_ushort),('scan',ctypes.c_ushort),('flags',ctypes.c_ulong),('time',ctypes.c_ulong),('extra',ctypes.c_size_t)]
 class Payload(ctypes.Union):
  _fields_=[('keyboard',Keyboard),('padding',ctypes.c_byte*32)]
 class Input(ctypes.Structure):
  _fields_=[('type',ctypes.c_ulong),('payload',Payload)]
 hwnd=focus();u.SetForegroundWindow(hwnd);time.sleep(.1)
 active=ctypes.c_ulong();u.GetWindowThreadProcessId(u.GetForegroundWindow(),ctypes.byref(active))
 if active.value!=p.pid:
  capture.record_event('synthetic_input_skipped',reason='emulator_not_foreground',vk_code=vk)
  return False
 event=Input();event.type=1;event.payload.keyboard.scan=u.MapVirtualKeyW(vk,0);event.payload.keyboard.flags=8
 capture.record_event('synthetic_input_requested',vk_code=vk)
 assert u.SendInput(1,ctypes.byref(event),ctypes.sizeof(event))==1
 try:time.sleep(.08)
 finally:
  event.payload.keyboard.flags=10
  assert u.SendInput(1,ctypes.byref(event),ctypes.sizeof(event))==1
 return True
def closed_normally(process, timeout=1):
 # A quit can disconnect GDB before Qt finishes shutting down. Only a verified
 # successful emulator exit counts as cancellation; keep crashes/errors visible.
 if process is None:return False
 try:return process.wait(timeout=timeout)==0
 except subprocess.TimeoutExpired:return False

def reach(address,keycode=None,delay=0,timeout=65):
 addresses=address if isinstance(address,tuple) else (address,)
 for a in addresses:assert command(f'Z1,{a:x},4')=='OK'
 packet('c')
 if keycode is not None:time.sleep(delay);key(keycode)
 try:reply=response(timeout)
 except TimeoutError:
  s.sendall(b'\x03');response(5)
  print('DUCK_TIMEOUT_PC '+command('p25'),flush=True)
  raise
 assert reply.startswith(('T','S')),reply
 for a in addresses:assert command(f'z1,{a:x},4')=='OK'
 pc=int.from_bytes(bytes.fromhex(command('p25')),'little')
 if pc not in addresses:print('DUCK_UNEXPECTED_STOP '+json.dumps({'reply':reply,'pc':hex(pc),'process_exit':p.poll()}),flush=True)
 assert pc in addresses,hex(pc)
 print('DUCK_MARKER '+hex(pc),flush=True)
 return pc
try:
 settings=configparser.ConfigParser(interpolation=None);settings.optionxform=str;settings.read_string(original.decode())
 from duckstation_keyboard import apply_stock_keyboard
 apply_stock_keyboard(settings)
 if args.auto_start:
  if not settings.has_section('Main'):settings.add_section('Main')
  settings.set('Main','ConfirmPowerOff','false')
 if checkpoint:
  if not settings.has_section('Main'):settings.add_section('Main')
  settings.set('Main','StartPaused','true')
 if not settings.has_section('Debug'):settings.add_section('Debug')
 settings.set('Debug','EnableGDBServer','true');settings.set('Debug','GDBServerPort','23456')
 if not settings.has_section('AutoUpdater'):settings.add_section('AutoUpdater')
 settings.set('AutoUpdater','CheckAtStartup','false')
 if selected_audio is not None:
  if not settings.has_section('Audio'):settings.add_section('Audio')
  settings.set('Audio','OutputDevice',selected_audio.endpoint_id)
 if args.pre_frame_sleep is not None:
  if not settings.has_section('Display'):settings.add_section('Display')
  settings.set('Display','PreFrameSleep','true' if args.pre_frame_sleep=='on' else 'false')
 if args.audio_buffer_ms is not None:
  if not settings.has_section('Audio'):settings.add_section('Audio')
  settings.set('Audio','BufferMS',str(args.audio_buffer_ms))
 if args.saved_memory_cards:
  from duckstation_cards import configure_player_cards
  configure_player_cards(root,settings)
 if args.no_card_flow_check or args.volatile_card_flow_check or args.campaign_check or checkpoint:
  from duckstation_cards import configure_test_cards
  configure_test_cards(settings,nonpersistent=args.volatile_card_flow_check)
 if args.card_screen_capture or args.hud_check or args.handoff_frame_check or args.handoff_stage2_check or args.handoff_stage6_check:
  screenshots=root/'logs'/'duck-screenshots'/stamp
  screenshots.mkdir(parents=True,exist_ok=False)
  for section in ('Folders','Hotkeys'):
   if not settings.has_section(section):settings.add_section(section)
  settings.set('Folders','Screenshots',str(screenshots))
  settings.set('Hotkeys','Screenshot','Keyboard/F10')
 checkpoint_folder=None
 if args.save_checkpoints:
  checkpoint_folder=root/'logs/duck-checkpoints'/stamp
  checkpoint_folder.mkdir(parents=True,exist_ok=False)
  for section in ('Folders','Hotkeys','Main'):
   if not settings.has_section(section):settings.add_section(section)
  settings.set('Folders','SaveStates',str(checkpoint_folder))
  settings.set('Main','EnableGlobalStates','true')
  for stage in range(1,7):
   settings.set('Hotkeys','SaveGlobalState'+str(stage),'Keyboard/F'+str(stage))
   settings.set('Hotkeys','SaveGameState'+str(stage),'Keyboard/F'+str(12+stage))
  settings.set('Hotkeys','SaveGameState7','Keyboard/F20')
  settings.set('Hotkeys','LoadGlobalState1','Keyboard/F19')
 if not settings.has_section('Logging'):settings.add_section('Logging')
 settings.set('Logging','LogToFile','true' if write_diagnostics else 'false')
 serialized=io.StringIO();settings.write(serialized);temporary=serialized.getvalue()
 if args.auto_controller:
  from duckstation_controller import add_automatic_controller_bindings
  temporary=add_automatic_controller_bindings(temporary)
 cfg.write_text(temporary)
 launch_args=[str(folder/'duckstation-qt-x64-ReleaseLTCG.exe'),'-batch','-nofullscreen']
 if checkpoint:launch_args.extend(['-statefile',checkpoint['path']])
 launch_args.extend(['--',str(disc_path)])
 if write_diagnostics:
  (root/'logs').mkdir(parents=True,exist_ok=True)
  launch_log=out.with_suffix('.stdout.txt').open('x')
 else:launch_log=contextlib.nullcontext(subprocess.DEVNULL)
 with launch_log as f:
  p=subprocess.Popen(launch_args,cwd=folder,stdout=f,stderr=subprocess.STDOUT)
  deadline=time.monotonic()+15
  while time.monotonic()<deadline:
   if p.poll() is not None:raise RuntimeError('DuckStation exited before connection')
   try:s=socket.create_connection(('127.0.0.1',23456),timeout=.5);break
   except OSError:time.sleep(.1)
  assert s,'GDB server unavailable'
  # Connection pauses the core; query consumes the explicit stop response.
  reply=command('?');print('DUCK_CONNECTED '+reply,flush=True)
  if not checkpoint:
   # Validate bytes loaded by DuckStation, independent of the disc container.
   # The breakpoint stops before the game's first instruction mutates data.
   from duckstation_identity import ENTRY_POINT,LOAD_ADDRESS,verify_loaded_game
   from duckstation_memory import ReadOnlyRAM
   try:reach(ENTRY_POINT,timeout=45)
   except (TimeoutError,AssertionError) as error:
    raise GameIdentityError('Could not verify the supported US PaRappa version. '
                     'Check that this image is complete and loads in DuckStation.') from error
   identity_anchors=[(a-0x80000000,bytes.fromhex(command(f'm{a:x},20')))
                     for a in (LOAD_ADDRESS,ENTRY_POINT)]
   identity_ram=ReadOnlyRAM(p.pid,identity_anchors,folder/'duckstation-qt-x64-ReleaseLTCG.exe')
   try:verify_loaded_game(identity_ram.read)
   finally:identity_ram.close()
   print('DUCK_GAME_IDENTITY_PASS SCUS-94183',flush=True)
  if checkpoint:
   # This build loads the state before starting its GDB server. StartPaused
   # keeps that state intact while the read-only observer is initialized.
   pass
  elif args.from_boot:
   reach(0x80016bfc)
   assert command('m80016bfc,8')=='960004343c000534'
   if not args.auto_start and not args.check and not args.benchmark_check:
    speech.say('Game ready. Press Enter here to start. Then switch to DuckStation. Arrows navigate. K confirms. Enter is Start and skips scenes.')
    input('Press Enter to start: ')
   u.SetForegroundWindow(focus())
   boot_hint_thread=threading.Thread(target=watch_boot_hint,daemon=True)
   boot_hint_thread.start()
   speech.say('Sony Computer Entertainment America Presents.')
   reach(0x80016c44)
   assert command('m80016c44,8')=='960004343c000534'
   speech.say('Masaya Matsuura Presents.')
   reach(0x801c4260)
   reach(0x801c455c)
   boot_hint='Start Skip.'
   speech.say('Opening scene.')
   branch=reach((0x801c4b50,0x801c4cd4),timeout=240)
   if branch==0x801c4b50:
    speech.say('Title animation.')
    reach(0x801c4cd4,timeout=180)
   boot_hint='';boot_hint_stop.set();boot_hint_thread.join(timeout=1)
  else:
   reach(0x801c4260)
   reach(0x801c455c)
   branch=reach((0x801c4b50,0x801c4cd4),0x0d,2)
   if branch==0x801c4b50:reach(0x801c4cd4,0x0d,.2)
  title_selector=None
  if checkpoint:
   pass
  elif args.from_title:
   reach(0x801c4d24)
   assert int.from_bytes(bytes.fromhex(command('p11')),'little')==0x801c3640
   title_selector=int.from_bytes(bytes.fromhex(command('p1d')),'little')+0x10
   assert 0x80000000<=title_selector<=0x801ffffc
   assert int.from_bytes(bytes.fromhex(command(f'm{title_selector:x},4')),'little') in (0,1)
  else:
   reach(0x801c7284,0x4b,.2)
   reach(0x801c77c0)
   if not args.scene_check:reach(0x801c7a60,0x0d,2)
   assert command('m801c7a60,4')=='c8ffbd27'
  from duckstation_memory import ReadOnlyRAM
  addresses=(0x80010000,0x80026b94,0x80054550) if args.from_title or checkpoint else (0x80010000,0x801c7a60,0x801cfa54)
  anchors=[(a-0x80000000,bytes.fromhex(command(f'm{a:x},20'))) for a in addresses]
  ram=ReadOnlyRAM(p.pid,anchors,folder/'duckstation-qt-x64-ReleaseLTCG.exe')
  print('DUCK_RAM_MATCHES '+str(len(ram.matches))+' method='+ram.method,flush=True)
  assert ram.read(addresses[1],32)==anchors[1][1]
  if args.register_check or args.card_check or not args.check:
   first=bytes.fromhex(command('g')[:256])
   location=ram.discover_registers(first)
   assert ram.read_registers()==first
   assert ram.read_program_counter()==int.from_bytes(bytes.fromhex(command('p25')),'little')
   for _ in range(5):
    assert command('s').startswith(('T','S'))
   second=bytes.fromhex(command('g')[:256])
   assert first!=second,'Second register sample must be independent'
   assert ram.read_registers()==second,'Register anchor did not track execution'
   assert ram.read_program_counter()==int.from_bytes(bytes.fromhex(command('p25')),'little')
   ram.cpu_context_verified=True
   print('DUCK_REGISTER_ANCHORS_PASS host_address='+hex(location),flush=True)
  print(('DUCK_CHECKPOINT_READY' if checkpoint else 'DUCK_TITLE_READY' if args.from_title else 'DUCK_STAGE1_READY')+' paused=true controls=L/K/J/I/Q/E',flush=True)
  if args.scene_check:
   (root/'logs'/('duck-card-code-'+stamp+'.json')).write_text(json.dumps({'address':0x801c77c0,'hex':ram.read(0x801c77c0,0x2a0).hex()}))
  if args.practice_check:
   (root/'logs'/('duck-practice-code-'+stamp+'.json')).write_text(json.dumps({'address':0x800276ec,'hex':ram.read(0x800276ec,0x8a0).hex()}))
  if not args.check:
   from duckstation_capture import DuckStationCapture,NullCapture
   from duckstation_cues import CueSounds
   from duckstation_monitor import Stage1Monitor
   session=None
   if args.diagnostics or args.benchmark_check:
    session=root/'logs/duck-sessions'/stamp
    session.mkdir(parents=True,exist_ok=False)
   cues=CueSounds(root,session,enabled=not args.mute_cues,output_name=args.cue_output,
                  handoff_enabled=args.handoff_sound,volume_percent=args.cue_volume,
                  export_wavs=bool(args.benchmark_check))
   if not args.benchmark_check and not args.auto_start and not args.from_boot:
    speech.say((f"Stage {checkpoint['stage']} {checkpoint['kind']} ready. " if checkpoint else 'Title screen ready. ' if args.from_title else 'Stage 1 ready. ')+'Press Enter here to play. '+('Text diagnostics are on. ' if args.diagnostics else '')+('Teacher cues are muted. ' if args.mute_cues else 'Teacher cues are enabled. ')+'Z reads your score.')
    input('Press Enter here to play: ')
   native_session=bool(args.from_title or checkpoint) and not args.benchmark_check
   observation_seconds=3600 if native_session else max(180,args.benchmark_check+10)
   if args.benchmark_check:
    capture=DuckStationCapture(session,p.pid,args.loopback_name,event_cap=600000 if args.campaign_check or args.volatile_overwrite_check or native_session else 60000,queue_size=2048,
                              audio_seconds=min(900,observation_seconds))
   elif args.diagnostics:
    capture=DuckStationCapture(session,p.pid,args.loopback_name,event_cap=60000,queue_size=2048,
                              record_audio=False,public_diagnostics=True)
   else:
    capture=NullCapture(p.pid)
   if session:
    print(('Benchmark' if args.benchmark_check else 'Diagnostics')+' session: '+str(session),flush=True)
   capture.start() # Readiness must succeed before resuming the game.
   if checkpoint:capture.record_event('checkpoint_loaded',checkpoint=checkpoint)
   if args.handoff_observe:
    capture.record_event('handoff_wait_code',regions={hex(address):ram.read(address,size).hex() for address,size in
                         ((0x80035560,0x240),(0x80040370,0x100),(0x8001e3b0,88))})
   if args.card_check:
    capture.record_event('card_wait_code',regions={hex(address):ram.read(address,size).hex() for address,size in
                         ((0x8001ea00,0xa0),(0x80035500,0x220))})
   def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
   if args.diagnostics and not args.benchmark_check:
    executable=folder/'duckstation-qt-x64-ReleaseLTCG.exe'
    support={'schema_version':1,'diagnostics':'text_only','audio_loopback_recorded':False,
       'emulator_executable':executable.name,'emulator_sha256':sha(executable),
       'script_sha256':{path.name:sha(path) for path in sorted((root/'scripts').glob('duckstation*.py'))
                        if not path.name.startswith('test_')}}
    (session/'support.json').write_text(json.dumps(support,indent=2))
   if args.benchmark_check:
    bios_name=settings.get('BIOS','PathNTSCU',fallback='').strip()
    bios_path=Path(bios_name) if bios_name else None
    if bios_path is not None and not bios_path.is_absolute():
     bios_dir=Path(settings.get('BIOS','SearchDirectory',fallback='bios'))
     if not bios_dir.is_absolute():bios_dir=folder/bios_dir
     bios_path=bios_dir/bios_path
    provenance=dict(executable_sha256=sha(folder/'duckstation-qt-x64-ReleaseLTCG.exe'),
       bios_sha256=sha(bios_path) if bios_path is not None and bios_path.is_file() else None,
       disc_file=Path(disc_path).name,disc_sha256=sha(disc_path),
       settings_overrides={'log_to_file':write_diagnostics,'audio_device_selected':selected_audio is not None,
          'cue_volume_percent':args.cue_volume,'teacher_cues_muted':args.mute_cues,
          'handoff_sound':args.handoff_sound,'saved_memory_cards':args.saved_memory_cards},
       cue_manifest=cues.manifest,ram_method=ram.method,
       input_method='developer chart replay' if args.developer_play or args.campaign_check else 'window key timing test' if args.input_latency_check else 'tagged SendInput test' if args.input_check else 'human keyboard' if not args.benchmark_check else 'no gameplay input',
       script_sha256={path.name:sha(path) for path in sorted((root/'scripts').glob('duckstation*.py'))},
       limitations=['OS hook is not the emulator input callback or physical key closure',
         'RAM input transitions are bounded by poll intervals; per-note judgments are raw, not decoded',
         'game tick changes are not presentation-frame measurements',
         'submission and loopback timestamps are not physical speaker latency'])
    (session/'benchmark.json').write_text(json.dumps(provenance,indent=2))
   developer=None
   campaign=None
   if args.campaign_check or args.volatile_overwrite_check:
    from duckstation_progression import MultiStageDeveloper,SCHEDULE_METADATA
    seeds=(root/'logs/passive-stage-seeds.lua').read_text()
    schedules={int(stage):[tuple(map(int,pair)) for pair in re.findall(r'\{\s*(\d+)\s*,\s*(\d+)\s*\}',body)] for stage,body in re.findall(r'\[(\d)\]\s*=\s*\{(.*?)\n    \}',seeds,re.S)}
    schedules[1]=[tuple(map(int,pair)) for pair in re.findall(r'\{\s*(\d+)\s*,\s*(\d+)\s*\}',(root/'logs/timing-stage1-seed.lua').read_text())]
    campaign=MultiStageDeveloper(p.pid,schedules)
    capture.record_event('campaign_schedule' if args.campaign_check else 'volatile_overwrite_schedule',metadata=SCHEDULE_METADATA,seed_hashes={name:sha(root/name) for name in set(SCHEDULE_METADATA['source_files'].values())})
   if args.developer_play and not args.volatile_overwrite_check:
    from duckstation_developer import DeveloperController
    schedule=[tuple(map(int,pair)) for pair in re.findall(r'\{(\d+),(\d+)\}',(root/'logs/timing-stage1-seed.lua').read_text())]
    assert len(schedule)==53
    developer=DeveloperController(p.pid,schedule)
   monitor=Stage1Monitor(ram,capture,cues,p.pid,speech,seconds=observation_seconds,
                         title_selector_address=title_selector,developer=developer,campaign=campaign)
   monitor.handoff_observe=args.handoff_observe
   monitor.handoff_sound=args.handoff_sound
   if not args.benchmark_check:
    u.SetForegroundWindow(focus())
    if not args.from_boot:
     speech.say('Playing. Switch to DuckStation. Close DuckStation when finished.'+(' Text diagnostics are on.' if args.diagnostics else ''))
   monitor.start();capture.set_armed(True)
   capture.record_event('resume_requested',debugger_detach=True)
   packet('c');s.close();s=None
   if not args.benchmark_check:
    if args.smoke_seconds:
     try:p.wait(timeout=args.smoke_seconds)
     except subprocess.TimeoutExpired:
      u.PostMessageW(focus(),0x10,0,0)
      p.wait(timeout=8)
    else:p.wait()
   else:
    if args.handoff_frame_check or args.handoff_stage2_check or args.handoff_stage6_check:
     def connect_probe():
      global s
      s=socket.create_connection(('127.0.0.1',23456),timeout=2)
      command('?')
     def disconnect_probe():
      global s
      packet('c');s.close();s=None
    if args.handoff_frame_check:
     from duckstation_handoff_probe import capture_handoffs
     if args.handoff_native_frames:
      from duckstation_handoff_probe import capture_native_frames
      capture_native_frames(ram,capture,screenshots,command,reach,key,connect_probe,disconnect_probe,monitor)
     else:
      capture_handoffs(ram,capture,screenshots,command,reach,key,connect_probe,disconnect_probe,monitor,late_only=args.handoff_late_only,early_only=args.handoff_early_only)
    elif args.campaign_check:
     deadline=time.monotonic()+args.campaign_check;saved_prompt=False;last_retry=0;retries={};last_stage=None;skipped_scene=None;last_scene_skip=0;stage6_probed=False
     scene_skip_attempts={}
     checkpoints=None
     if args.save_checkpoints:
      from duckstation_checkpoints import CampaignCheckpoints
      checkpoints=CampaignCheckpoints(checkpoint_folder,key,capture.record_event)
      with (checkpoint_folder/'provenance.json').open('x') as checkpoint_info:
       json.dump(provenance,checkpoint_info,indent=2)
     while time.monotonic()<deadline and not (session/'stop-campaign').exists():
      if p.poll() is not None:break
      if monitor.error:raise RuntimeError(monitor.error)
      scene=monitor.card_context.scene
      if checkpoints:
       tick=int.from_bytes(ram.read(0x801c364c,4),'little')
       for cleared,score in list(monitor.completed_stages.items()):
        if (cleared,'clear') not in checkpoints.saved:
         checkpoints.save(cleared,'clear',tick,score)
       stage=monitor.current_stage
       if stage and 192<=tick<768 and (stage,'entry') not in checkpoints.saved:
        checkpoints.save(stage,'entry',tick,monitor.score)
        print('DUCK_CHECKPOINT_ENTRY '+str(stage),flush=True)
        if stage==1:
         # Verify the first new checkpoint really reloads before investing in
         # the campaign. Both save and load happen before the first teacher cue.
         before_load=int.from_bytes(ram.read(0x80057034,4),'little')
         key(0x82) # F19: load the matching first entry slot.
         load_deadline=time.monotonic()+3
         while time.monotonic()<load_deadline:
          if int.from_bytes(ram.read(0x80057034,4),'little')<before_load:break
          time.sleep(.005)
         else:raise RuntimeError('First checkpoint reload was not verified')
         capture.record_event('checkpoint_reload_verified',stage=1)
         print('DUCK_CHECKPOINT_RELOAD_VERIFIED',flush=True)
       if monitor.last_scene==7 and 6 in monitor.completed_stages:
        checkpoints.save(6,'ending',tick,monitor.completed_stages[6])
        break
      if scene is not None:skipped_scene=scene
      scene_tick=int.from_bytes(ram.read(0x801c364c,4),'little')
      if (skipped_scene is not None and monitor.current_stage==min(skipped_scene,6)
          and not monitor.retry_active and scene_skip_attempts.get(skipped_scene,0)<2
          and (scene_tick<192 or scene_tick>=0xffff0000) and time.monotonic()-last_scene_skip>=2):
       capture.record_event('campaign_skip_scene',scene=skipped_scene,vk_code=0x0d)
       key(0x0d);last_scene_skip=time.monotonic()
       scene_skip_attempts[skipped_scene]=scene_skip_attempts.get(skipped_scene,0)+1
      elif 192<=scene_tick<768:skipped_scene=None
      if monitor.current_stage and monitor.current_stage!=last_stage:
       last_stage=monitor.current_stage;print('DUCK_CAMPAIGN_STAGE '+str(last_stage),flush=True)
      if args.handoff_stage2_check and monitor.current_stage==2:
       tick=int.from_bytes(ram.read(0x801c364c,4),'little')
       if 192<=tick<1850:
        from duckstation_handoff_probe import capture_native_frames
        capture.record_event('handoff_stage2_code',address=0x801cb170,code_hex=ram.read(0x801cb170,0x1400).hex())
        capture_native_frames(ram,capture,screenshots,command,reach,key,connect_probe,disconnect_probe,monitor,start_tick=1850,end_tick=1900)
        capture_native_frames(ram,capture,screenshots,command,reach,key,connect_probe,disconnect_probe,monitor,start_tick=5110,end_tick=5165)
        break
      if args.handoff_stage6_check and not stage6_probed and monitor.current_stage==6:
       tick=int.from_bytes(ram.read(0x801c364c,4),'little')
       if 192<=tick<6450:
        from duckstation_handoff_probe import capture_native_frames
        capture_native_frames(ram,capture,screenshots,command,reach,key,connect_probe,disconnect_probe,monitor,start_tick=6450,end_tick=6510)
        capture_native_frames(ram,capture,screenshots,command,reach,key,connect_probe,disconnect_probe,monitor,start_tick=14330,end_tick=14385)
        stage6_probed=True
        if not checkpoints:break
      card=monitor.cards._context
      if card is not None and card[0]==2:
       if not saved_prompt:
        time.sleep(.5);capture.record_event('campaign_decline_save',stage=last_stage);key(0x4c);saved_prompt=True
      else:saved_prompt=False
      if monitor.retry_active and time.monotonic()-last_retry>4 and monitor.card_context.modal is not None and monitor.card_context.modal[0]==4:
       retries[last_stage]=retries.get(last_stage,0)+1
       assert retries[last_stage]<=5,'Campaign retry budget exhausted for stage '+str(last_stage)
       capture.record_event('campaign_retry',stage=last_stage,attempt=retries[last_stage],score=monitor.score)
       key(0x4b);last_retry=time.monotonic()
      time.sleep(.05)
     capture.record_event('campaign_finished',completed_stages=monitor.completed_stages,retries=retries)
     print('DUCK_CAMPAIGN_RESULTS '+json.dumps(monitor.completed_stages),flush=True)
    elif args.no_card_flow_check:
     deadline=time.monotonic()+args.benchmark_check;accepted=False
     while time.monotonic()<deadline:
      card=monitor.cards._context
      if not accepted and card is not None and card[0]==2:
       time.sleep(.5)
       capture.record_event('no_card_save_prompt_confirmed',card_mode='None')
       key(0x4b);accepted=True
      time.sleep(.05)
     assert accepted,'Save question was not reached'
    elif args.volatile_card_flow_check:
     from duckstation_card_speech import SLOT_STATE
     from duckstation_menu import NAME_STATE
     deadline=time.monotonic()+args.benchmark_check

     def wait_card_state(mode,state_pointer,label,observe=None,matches=None,seconds=15):
      end=min(deadline,time.monotonic()+seconds)
      while time.monotonic()<end:
       context=monitor.cards._context
       if (context is not None and context[0]==mode
           and (state_pointer is None or context[1]==state_pointer)):
        value=observe() if observe is not None else None
        if matches is None or matches(value):return value
       time.sleep(.025)
      raise AssertionError(label)

     wait_card_state(2,None,'Save question was not reached',seconds=args.benchmark_check-30)
     time.sleep(.5)
     assert monitor.cards._context is not None and monitor.cards._context[0]==2,'Save question closed before confirmation'
     capture.record_event('volatile_card_save_prompt_confirmed',card_mode='NonPersistent')
     capture.record_event('volatile_card_key_requested',phase='accept_save_prompt',vk_code=0x4b)
     key(0x4b)

     slot=wait_card_state(11,SLOT_STATE,'Save slot list was not reached',
                          lambda:monitor.cards._slot_observation(SLOT_STATE,11),
                          lambda value:value is not None and value['cursor']==0 and value['item']=='Empty slot 1')
     capture.record_event('volatile_card_empty_slot_selected',cursor=slot['cursor'],item=slot['item'])
     time.sleep(.5)
     assert monitor.cards._context==(11,SLOT_STATE),'Save slot context changed before selection'
     capture.record_event('volatile_card_key_requested',phase='select_empty_slot',vk_code=0x4b)
     key(0x4b)

     name=wait_card_state(10,NAME_STATE,'Verified name-entry keyboard was not reached',
                          lambda:monitor.cards._name_observation(NAME_STATE),
                          lambda value:value is not None and value['name']=='' and value['code']==ord('A'))
     capture.record_event('volatile_card_name_entry',cursor=name['cursor'],code=name['code'],name=name['name'])
     time.sleep(.5)
     assert monitor.cards._context==(10,NAME_STATE),'Name-entry context changed before typing'
     capture.record_event('volatile_card_key_requested',phase='type_name_a',vk_code=0x4b)
     key(0x4b)
     name=wait_card_state(10,NAME_STATE,'Name A was not entered into the verified keyboard state',
                          lambda:monitor.cards._name_observation(NAME_STATE),
                          lambda value:value is not None and value['name']=='A' and value['code']==ord('A'))
     capture.record_event('volatile_card_name_entered',cursor=name['cursor'],code=name['code'],name=name['name'])
     time.sleep(.5)
     assert monitor.cards._context==(10,NAME_STATE),'Name-entry context changed before End selection'
     capture.record_event('volatile_card_key_requested',phase='select_name_end',vk_code=0x25)
     key(0x25)
     end=wait_card_state(10,NAME_STATE,'Name End key was not reached',
                         lambda:monitor.cards._name_observation(NAME_STATE),
                         lambda value:value is not None and value['name']=='A' and value['code']==10)
     capture.record_event('volatile_card_name_end_selected',cursor=end['cursor'],code=end['code'],name=end['name'])
     time.sleep(.5)
     assert monitor.cards._context==(10,NAME_STATE),'Name-entry context changed before save confirmation'
     capture.record_event('volatile_card_key_requested',phase='confirm_name_end',vk_code=0x4b)
     key(0x4b)

     if args.card_screen_capture and not args.volatile_overwrite_check:
      from duckstation_ui_context import CardContext
      probe=CardContext(ram);save_deadline=min(deadline,time.monotonic()+10)
      while time.monotonic()<save_deadline:
       if probe.poll()==(15,NAME_STATE):
        capture.record_event('screenshot_requested',directory=str(screenshots),method='emulator GPU screenshot on F10 release',mode=15)
        key(0x79);break
       time.sleep(.025)
      else:raise AssertionError('Save operation screen was not reached')
     # Saving proceeds to the next stage, not back to the slot list.
     while monitor.current_stage!=2 and time.monotonic()<deadline:
      time.sleep(.05)
     assert monitor.current_stage==2,'Native save flow did not continue to Stage 2'
     capture.record_event('volatile_card_save_flow_return',card_mode='NonPersistent',stage=2,name='A')
     if args.volatile_overwrite_check:
      wait_card_state(2,None,'Second Save question was not reached after Stage 2',
                      seconds=max(0,deadline-time.monotonic()-30))
      time.sleep(.5)
      assert monitor.cards._context is not None and monitor.cards._context[0]==2,'Second Save question closed before overwrite check'
      capture.record_event('volatile_card_second_save_prompt_observed',card_mode='NonPersistent',stage=2)
      capture.record_event('volatile_card_key_requested',phase='accept_second_save_prompt',vk_code=0x4b)
      key(0x4b)

      slot=wait_card_state(11,SLOT_STATE,'Second Save slot list was not reached',
                           lambda:monitor.cards._slot_observation(SLOT_STATE,11),
                           lambda value:value is not None and (value['cursor']==15 or
                               value['cursor']==0 and value['item']=='A'))
      time.sleep(.5)
      assert monitor.cards._context==(11,SLOT_STATE),'Second Save slot context changed before overwrite selection'
      slot=monitor.cards._slot_observation(SLOT_STATE,11)
      assert slot is not None and slot['cursor'] in (0,15),'Second Save slot cursor was not verified'
      if slot['cursor']==15:
       capture.record_event('volatile_card_key_requested',phase='wrap_to_first_overwrite_slot',vk_code=0x28)
       key(0x28)
       slot=wait_card_state(11,SLOT_STATE,'Occupied slot A was not selected after wrapping',
                            lambda:monitor.cards._slot_observation(SLOT_STATE,11),
                            lambda value:value is not None and value['cursor']==0 and value['item']=='A')
      assert slot is not None and slot['cursor']==0 and slot['item']=='A','First save slot A was not selected for overwrite'
      capture.record_event('volatile_card_overwrite_slot_selected',cursor=slot['cursor'],item=slot['item'])
      time.sleep(.5)
      assert monitor.cards._context==(11,SLOT_STATE),'Second Save slot context changed before selection'
      slot=monitor.cards._slot_observation(SLOT_STATE,11)
      assert slot is not None and slot['cursor']==0 and slot['item']=='A','First save slot A changed before overwrite selection'
      capture.record_event('volatile_card_key_requested',phase='select_slot_a_for_overwrite',vk_code=0x4b)
      key(0x4b)

      from duckstation_ui_context import CardContext
      probe=CardContext(ram);overwrite_deadline=min(deadline-2,time.monotonic()+15)
      overwrite_observed=False
      while time.monotonic()<overwrite_deadline:
       if probe.poll()==(22,SLOT_STATE):
        overwrite_observed=True;break
       time.sleep(.025)
      assert overwrite_observed,'Raw card context did not reach the overwrite confirmation'
      capture.record_event('volatile_card_overwrite_observed',mode=22,state_pointer=hex(SLOT_STATE),
                           slot=1,name='A',confirmation_sent=False)
      capture.record_event('screenshot_requested',directory=str(screenshots),
                           method='emulator GPU screenshot on F10 release',mode=22)
      key(0x79)
      time.sleep(2)
     else:
      time.sleep(max(0,deadline-time.monotonic()))
    elif args.menu_check:
     deadline=time.monotonic()+args.benchmark_check
     # Native controls only: title Menu, Language, return, Difficulty, Stage.
     # The title-to-main animation takes about six seconds in this build.
     for delay,vk in ((2,0x27),(2,0x4b),(9,0x26),(.5,0x26),(.5,0x26),(1,0x4b),
                      (3,0x28),(1,0x28),(1,0x4b),(3,0x28),(1,0x28),(1,0x4c),(1,0x4b),
                      (1,0x28),(1,0x4b),(3,0x28)):
      time.sleep(delay);capture.record_event('menu_key_requested',vk_code=vk);key(vk)
     if args.benchmark_check>=50:
      # Main Exit returns through the opening; Start skips it to the title.
      for delay,vk in ((1,0x4b),(3,0x28),(1,0x4b)):
       time.sleep(delay);capture.record_event('menu_key_requested',vk_code=vk);key(vk)
      while monitor.card_context.title_selector is None and time.monotonic()<deadline-4:
       assert monitor.current_stage is None,'Menu return unexpectedly entered a rhythm stage'
       capture.record_event('menu_key_requested',vk_code=0x0d);key(0x0d);time.sleep(2)
      assert monitor.card_context.title_selector is not None,'Fresh title context was not reached'
      key(0x48);time.sleep(.5);key(0x27)
     time.sleep(max(0,deadline-time.monotonic()))
    elif args.practice_check:
     deadline=time.monotonic()+args.benchmark_check
     for delay,vk in ((2,0x27),(2,0x4b),(9,0x4a)):
      time.sleep(delay);capture.record_event('practice_key_requested',vk_code=vk);key(vk)
     for delay in (8,3,4):
      time.sleep(delay);capture.record_event('practice_key_requested',vk_code=0x49);key(0x49)
     time.sleep(max(0,deadline-time.monotonic()-12))
     capture.record_event('practice_key_requested',vk_code=0x4b);key(0x4b)
     # The visible question has a display-only interval before input opens.
     # Wait for its actual controller loop rather than guessing that delay.
     while monitor.card_context.practice_wait!=0x80027ea0 and time.monotonic()<deadline-4:
      time.sleep(.02)
     assert monitor.card_context.practice_wait==0x80027ea0,'Practice exit controls did not become active'
     capture.record_event('practice_key_requested',vk_code=0x4b);key(0x4b)
     time.sleep(max(0,deadline-time.monotonic()))
    elif args.card_check:
     deadline=time.monotonic()+args.benchmark_check
     for delay,vk in ((2,0x27),(2,0x4b)):
      time.sleep(delay);capture.record_event('card_key_requested',vk_code=vk);key(vk)
     time.sleep(9)
     s=socket.create_connection(('127.0.0.1',23456),timeout=2);command('?')
     if args.card_action=='highscores':
      packet('c');s.close();s=None
      for vk in (0x26,0x26):
       key(vk);time.sleep(.5)
      s=socket.create_connection(('127.0.0.1',23456),timeout=2);command('?')
     pc=reach((0x80026b94,0x800191e4),{'load':0x49,'replay':0x4c,'highscores':0x4b}[args.card_action],.1,timeout=10)
     registers={name:command('p'+index) for name,index in (('a0','4'),('a1','5'),('a2','6'),('ra','1f'),('sp','1d'))}
     capture.record_event('card_entry_probe',pc=pc,registers=registers)
     print('DUCK_CARD_ENTRY '+json.dumps(registers),flush=True)
     packet('c');s.close();s=None
     # Wait for the actual slot context; loading duration varies by card.
     ready_deadline=min(deadline-6,time.monotonic()+15)
     if args.replay_playback_check or args.load_selection_check:
      from duckstation_card_speech import SLOT_STATE
      slot_mode=12 if args.load_selection_check else 13
      slot_action='load' if args.load_selection_check else 'replay'
      def read_action_slot():
       if monitor.cards._context!=(slot_mode,SLOT_STATE):return None
       return monitor.cards._slot_observation(SLOT_STATE,slot_mode)
      def wait_action_slot(matches,message):
       stop=min(deadline,time.monotonic()+15)
       while time.monotonic()<stop:
        slot=read_action_slot()
        if matches(slot):return slot
        time.sleep(.025)
       raise AssertionError(message)
      while monitor.cards._context!=(slot_mode,SLOT_STATE) and time.monotonic()<ready_deadline:
       time.sleep(.025)
      assert monitor.cards._context==(slot_mode,SLOT_STATE),slot_action.title()+' slot context was not reached'
      exit_slot=wait_action_slot(lambda slot:slot is not None and slot['cursor']==15 and slot['item']=='Exit',
                                 slot_action.title()+' menu did not show its default Exit selection')
      capture.record_event(slot_action+'_exit_selection_verified',cursor=exit_slot['cursor'],item=exit_slot['item'])
      time.sleep(.5)
      assert read_action_slot()==exit_slot,slot_action.title()+' selection changed before navigation'
      capture.record_event(slot_action+'_key_requested',phase='wrap_to_first_slot',vk_code=0x28)
      key(0x28)
      selected=wait_action_slot(lambda slot:slot is not None and slot['cursor']==0,
                                'Down did not wrap from Exit to '+slot_action+' slot 1')
      assert not selected['item'].startswith('Empty slot '),slot_action.title()+' slot 1 is empty; no selection was started'
      capture.record_event(slot_action+'_saved_slot_selected',cursor=selected['cursor'],name=selected['item'],
                           **({'action':slot_action} if slot_action=='load' else {}))
      time.sleep(.5)
      assert read_action_slot()==selected,slot_action.title()+' slot changed before selection'
      phase='start_read_only_playback' if slot_action=='replay' else 'load_saved_slot'
      capture.record_event(slot_action+'_key_requested',phase=phase,vk_code=0x4b,name=selected['item'],
                           **({'action':slot_action} if slot_action=='load' else {}))
      key(0x4b)
      if slot_action=='replay':
       capture.record_event('replay_playback_observation_started',name=selected['item'],card_action=slot_action)
      else:
       capture.record_event('load_selection_started',name=selected['item'],card_action=slot_action,cursor=selected['cursor'])
       if args.card_screen_capture:
        from duckstation_ui_context import CardContext
        probe=CardContext(ram);loading_deadline=min(deadline,time.monotonic()+5)
        while time.monotonic()<loading_deadline:
         if probe.poll()==(16,SLOT_STATE):
          capture.record_event('screenshot_requested',directory=str(screenshots),method='emulator GPU screenshot on F10 release',mode=16)
          key(0x79);break
         time.sleep(.01)
        else:raise AssertionError('Native loading screen was not observed')
      while time.monotonic()<deadline:
       assert p.poll() is None,'DuckStation exited during '+slot_action+' selection check'
       assert not monitor.error,monitor.error
       time.sleep(.05)
     else:
      while args.card_action!='highscores' and not monitor.cards.hint() and time.monotonic()<ready_deadline:
       time.sleep(.05)
      for delay,vk in ((2,0x48),(1,0x28),(1,0x26)):
       time.sleep(delay);capture.record_event('card_key_requested',vk_code=vk);key(vk)
      if args.card_screen_capture:
       capture.record_event('screenshot_requested',directory=str(screenshots),method='emulator GPU screenshot on F10 release')
       key(0x79)
      time.sleep(max(0,deadline-time.monotonic()))
    elif args.hud_check:
     deadline=time.monotonic()+args.benchmark_check
     targets=iter((2700,2800,2840,2895,3000,3500,4250));target=next(targets,None)
     while time.monotonic()<deadline and target is not None:
      state=ram.read(0x801c3640,0xb0)
      tick=int.from_bytes(state[12:16],'little')
      if target<=tick<100000:
       capture.record_event('hud_screenshot_requested',target_tick=target,tick=tick,
                            state_hex=state.hex(),directory=str(screenshots))
       key(0x79)
       capture.record_event('hud_screenshot_released',state_hex=ram.read(0x801c3640,0xb0).hex())
       if target in (2700,3500,4250):synthetic_tap(0x46)
       target=next(targets,None)
      time.sleep(.005)
     assert target is None,'HUD capture targets were not reached'
     time.sleep(max(0,deadline-time.monotonic()))
    elif args.pause_check:
     deadline=time.monotonic()+args.benchmark_check
     time.sleep(8)
     capture.record_event('pause_key_requested',vk_code=0x0d)
     key(0x0d);time.sleep(.5)
     s=socket.create_connection(('127.0.0.1',23456),timeout=2)
     command('?')
     registers={name:command('p'+index) for name,index in (('a0','4'),('a1','5'),('a2','6'),('ra','1f'),('sp','1d'),('pc','25'))}
     stack=int.from_bytes(bytes.fromhex(registers['sp']),'little')
     capture.record_event('pause_dialog_probe',registers=registers,
                          descriptor_hex=ram.read(0x80054550,0x100).hex(),
                          common_hex=ram.read(0x800916d0,0x170).hex(),
                          stack_hex=ram.read(stack,min(0x100,0x80200000-stack)).hex()
                          if 0x80000000<=stack<0x80200000 else None)
     packet('c');s.close();s=None
     for delay,vk in ((2,0x28),(1,0x26),(1,0x27),(1,0x25),(2,0x4b)):
      time.sleep(delay);capture.record_event('pause_key_requested',vk_code=vk);key(vk)
     time.sleep(max(0,deadline-time.monotonic()))
    elif args.input_latency_check:
     deadline=time.monotonic()+args.benchmark_check
     time.sleep(17)
     for i in range(16):
      vk=(0x4b,0x49)[i%2]
      capture.record_event('window_input_requested',vk_code=vk,index=i)
      key(vk);time.sleep(.13+(i%3)*.013)
     time.sleep(max(0,deadline-time.monotonic()))
    elif args.input_check:
     time.sleep(20)
     for vk in (0x49,0x4b,0x4c):synthetic_tap(vk);time.sleep(.3)
     synthetic_tap(0x5a) # Verify Z score speech through an ordinary key event.
     capture.record_event('window_input_requested',vk_code=0x4b)
     key(0x4b)
     time.sleep(args.benchmark_check-23)
    else:time.sleep(args.benchmark_check)
    assert p.poll() is None,'DuckStation exited during benchmark check'
    assert not monitor.error,monitor.error
    print('DUCK_BENCHMARK_CHECK_COMPLETE',flush=True)
  else:
   packet('c');s.close();s=None
   time.sleep(2);assert p.poll() is None,'DuckStation exited after debugger detach'
   print('DUCK_DETACH_PASS',flush=True)
   speech.say('DuckStation preparation passed.')
except GameIdentityError as error:
 print('DUCK_GAME_IDENTITY_FAILED '+str(error),file=sys.stderr,flush=True)
 raise SystemExit(3)
except (AssertionError, OSError, RuntimeError):
 if args.auto_start and not args.check and not args.benchmark_check and closed_normally(p):
  print('DUCK_CLOSED_NORMALLY',flush=True)
 else:raise

finally:
 boot_hint_stop.set()
 if boot_hint_thread:boot_hint_thread.join(timeout=1)
 if monitor:monitor.stop()
 if capture:capture.stop()
 if cues:
  cues.close()
  if capture and capture.enabled and capture.session_dir:
   (capture.session_dir/'cue-output.json').write_text(json.dumps(cues.manifest,indent=2))
 if ram:ram.close()
 if p and p.poll() is None:p.terminate();p.wait(timeout=8)
 if s:s.close()
 cfg.write_bytes(original)
 if write_diagnostics and (folder/'duckstation.log').exists():out.with_suffix('.log').write_bytes((folder/'duckstation.log').read_bytes())
 if write_diagnostics and capture and capture.enabled and capture.session_dir and (folder/'duckstation.log').exists():
  (capture.session_dir/'duckstation.log').write_bytes((folder/'duckstation.log').read_bytes())
