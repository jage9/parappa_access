"""Stage 1 read-only benchmark observer. Poll times are not audible latencies."""
import ctypes
import queue
import statistics
import struct
import threading
import time
from duckstation_profiles import PROFILES,consumed_events as profile_events
from duckstation_keyboard import SCORE_VK,RATING_VK,HINT_VK,LYRICS_VK,SUBTITLES_VK
from duckstation_rating import RatingChanges,rating_name,rating_announcement,freestyle_active
from duckstation_subtitles import SubtitleReader,suppression_reason

STATE = 0x801c3640
GRID = 0x801cfa54
LANES = {1:'TRIANGLE',2:'CIRCLE',3:'X',4:'SQUARE',5:'L1',6:'L1',7:'R1',8:'R1'}
CURSORS = [('primary_a',0x94,0x8c,0x90,1),('primary_b',0x98,0x8e,0x90,2),
           ('response_a',0xa4,0x9e,0xa2,1),('response_b',0xa8,0xa0,0xa2,2)]
def word(data,offset): return struct.unpack_from('<I',data,offset)[0]
def short(data,offset): return struct.unpack_from('<h',data,offset)[0]

def stage_context(ram, roots, app):
    """Keep Replay recognizable for UI gating without authorizing its cues."""
    if app not in (0,2) or len(roots)!=8:return None,False
    profile=next((p for p in PROFILES.values() if p['grid']==word(roots,0) and p['count']==word(roots,4)),None)
    if profile is None:return None,False
    if (word(ram.read(profile['entry'],4),0)!=profile['entry_word']
            or word(ram.read(profile['loop'],4),0)!=profile['loop_word']):return None,False
    return (profile,False) if app==0 else (None,True)

def completed_scene_reset(had_events,previous_tick,tick,retry):
    # A newly loaded overlay can inherit a large title clock, and its negative
    # preroll is represented as an unsigned word. Neither is a finished round.
    return had_events and 3840<previous_tick<1_000_000 and tick<192 and not retry

def read_monitor_sample(ram, diagnostics):
    """Read the gameplay state; omit diagnostic-only byte snapshots when off."""
    a=ram.read(STATE,0xb0)
    common=ram.read(0x800916d0,0x170 if diagnostics else 0x148)
    result=(ram.read(0x8006ed74,4),ram.read(0x80092f10,64) if diagnostics else b'')
    roots=ram.read(0x800943d0,8)
    b=ram.read(STATE,0xb0)
    return a,common,result,roots,b

def consumed_events(previous,current,grid):
    """Only changed, already-incremented cursors; never extrapolate missed notes."""
    events=[]
    mode=short(current,0x8a)
    for name,po,io,ao,active in CURSORS:
        ptr,index=word(current,po),short(current,io)
        oldptr,oldindex=word(previous,po),short(previous,io)
        if (ptr,index)==(oldptr,oldindex): continue
        if not word(current,0)&8 or short(current,ao)!=active: continue
        if mode not in ((1,2) if active==1 else (2,)): continue
        if not 3<=index<=19: continue
        offset=ptr-GRID
        if not 0<=offset<36*44 or offset%44 not in (4,24): continue
        if ptr==oldptr and index!=oldindex+1:
            events.append(dict(cursor=name,rejected='index_jump',before=oldindex,after=index))
            continue
        lane=grid[offset+index-1]
        if lane in LANES:
            events.append(dict(cursor=name,button=LANES[lane],lane=lane,
                               pointer=ptr,index=index-1,tick=word(current,0xc),mode=mode,active=active))
    return events

CUE_POLL_GAP_NS=25_000_000
PROGRESS_BYTES=0x80092f1d      # six bytes, 3 = cleared on Cool (recorder 0x8001635C)
ALL_COOL_WORD=0x80092f44       # save struct +0x34, 1 when all six are 3
STAGE_SELECT_STATE=0x80087b78  # Stage Select init copies the bytes to +0x0E as u16s
def apply_all_cool(ram,stage_select):
    """Testing cheat: keep every stage cleared on Cool; return what was patched.

    The game's new-game reset (0x80015CC4) and a card load rewrite the save
    struct after the title, so a single write before play is lost. The
    Stage Select screen keeps its own copy, patched too while it is showing.
    """
    patched=[]
    if ram.read(PROGRESS_BYTES,6)!=b'\x03'*6:
        ram.write(PROGRESS_BYTES,b'\x03'*6);ram.write(ALL_COOL_WORD,b'\x01\x00\x00\x00');patched.append('save_struct')
    if stage_select and ram.read(STAGE_SELECT_STATE+0x0e,14)!=struct.pack('<7H',3,3,3,3,3,3,1):
        ram.write(STAGE_SELECT_STATE+0x0e,struct.pack('<7H',3,3,3,3,3,3,1));patched.append('stage_select')
    return patched

def cue_suppression_reason(profile,gap,freestyle):
    """Why a teacher note cue must not play now, or None to play it."""
    if not profile['cue_emission_enabled']:return 'pending_stage_validation'
    if freestyle:return 'cool_freestyle'
    if gap>CUE_POLL_GAP_NS:return 'poll_gap'
    return None

class Stage1Monitor:
    def __init__(self,ram,capture,cues,pid,speech=None,seconds=180,title_selector_address=None,developer=None,campaign=None):
        self.ram,self.capture,self.cues,self.pid=ram,capture,cues,pid
        self.seconds=seconds;self.speech=speech
        self.stop_event=threading.Event();self.thread=None
        self.spoken=queue.Queue(maxsize=8)
        self.error=None;self.summary={};self.score=0
        self.rating_changes=RatingChanges()
        from duckstation_menu import MenuReader
        # The startup selector is captured before the title draw loop runs.
        # Do not speak its copyright card over the preceding title animation;
        # acquire the selector from the live title/VSync context after resume.
        self.menu=MenuReader(ram)
        from duckstation_ui_context import CardContext
        from duckstation_card_speech import DuckStationCardSpeechReader
        self.card_context=CardContext(ram)
        self.cards=DuckStationCardSpeechReader(ram)
        from duckstation_practice_speech import PracticeSpeechReader
        self.practice=PracticeSpeechReader()
        self.developer=developer
        self.diagnostic_paused=False
        self.handoff_observe=False
        self.handoff_sound=False
        from duckstation_handoff import HandoffObserver
        self.handoff=HandoffObserver(ram)
        self.subtitles=SubtitleReader(ram)
        # Both start off; duckstation-compare applies the saved preferences.
        self.subtitles_enabled=False
        self.lyrics_enabled=False
        self.all_cool=False
        self.campaign=campaign;self.current_stage=None;self.retry_active=False;self.completed_stages={};self.last_scene=None
        self.u=ctypes.WinDLL('user32');self.u.GetForegroundWindow.restype=ctypes.c_void_p
        self.u.GetWindowThreadProcessId.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]

    def start(self):
        self.grid=self.ram.read(GRID,36*44)
        self.thread=threading.Thread(target=self._run,name='duck-ram-observer',daemon=True)
        self.speech_thread=threading.Thread(target=self._speech,name='duck-score-speech',daemon=True)
        self.speech_thread.start();self.thread.start()

    def _speech(self):
        while not self.stop_event.is_set():
            try:message,interrupt=self.spoken.get(timeout=.2)
            except queue.Empty:continue
            if self.speech:
                if interrupt:self.speech.say(message)
                else:self.speech.say(message,interrupt=False)

    def _say(self,message,interrupt=True):
        try:self.spoken.put_nowait((message,interrupt))
        except queue.Full:pass

    def _remember(self,**changes):
        """Save an in-game toggle so it holds for the next session."""
        try:
            from launcher_settings import update_settings
            update_settings(changes)
        except (OSError,ValueError) as error:
            self.capture.record_event('settings_save_failed',error=str(error))

    def _run(self):
        start=last_poll=last_change=time.perf_counter_ns()
        previous=None;last_common=None;last_pad=None;last_tick=None;last_context=None;last_input_tick=None;last_result=None;last_menu_raw=None
        gaps=[];read_costs=[];ticks=0;cue_count=0;torn=0;polls=0;paused=False;ekey=False;fkey=False;hkey=False;ykey=False;ukey=False;retry=False;last_menu=0;developer_started=False
        diagnostics=bool(getattr(self.capture,'diagnostics_enabled',True))
        record=self.capture.record_event;bounded=diagnostics;round_started=False
        active_card=None;card_seen=0;last_card_poll=0;highscores_active=False;highscores_seen=0
        announced_card_scene=None
        practice_active=False;practice_seen=0;last_practice_state=None
        title_active=self.menu._title_selector_address is not None;title_seen=start
        opening_active=False;opening_seen=0
        last_handoff_sample=None
        def stats(values):
            ordered=sorted(values)
            return {} if not ordered else dict(count=len(ordered),median_ns=statistics.median(ordered),
                p95_ns=ordered[int((len(ordered)-1)*.95)],max_ns=ordered[-1])
        def summary():
            return dict(polls=polls,unstable_reads=torn,game_tick_changes=ticks,cue_submissions=cue_count,
                        poll_gaps=stats(gaps),read_cost=stats(read_costs),error=self.error)
        try:
            while not self.stop_event.is_set():
                now=time.perf_counter_ns()
                if bounded and now-start>=self.seconds*1_000_000_000:
                    self.summary=summary();record('monitor_summary',**self.summary)
                    record('observation_limit',seconds=self.seconds,gameplay_and_cues_continue=True)
                    self.capture.set_armed(False)
                    bounded=False;record=lambda *args,**kwargs:None
                gap=now-last_poll;last_poll=now
                if bounded:gaps.append(gap);polls+=1
                before=time.perf_counter_ns()
                a,common,result_state,roots,b=read_monitor_sample(self.ram,diagnostics)
                end=time.perf_counter_ns()
                if bounded:read_costs.append(end-before)
                if a!=b:
                    torn+=1;time.sleep(.001);continue
                profile,replay_active=stage_context(self.ram,roots,short(common,0))
                context=profile is not None
                context_key=profile['stage'] if profile else None
                self.current_stage=context_key
                if context_key!=last_context:
                    record('stage_context',valid=context,stage=context_key,app=short(common,0),mode=short(common,10))
                    if last_context and not context and round_started:
                        # A recognized clear/reset already announced its score.
                        self._say(f'Score {self.score}.')
                    previous=None;last_context=context_key;self.cues.stop();round_started=False
                    if profile:
                        self.menu.reset(baseline_name=True)
                        self.grid=self.ram.read(profile['grid'],profile['count']*44)
                self.score=short(common,0x146)
                if diagnostics and common!=last_common:
                    record('common_state',perf_counter_ns=end,score=self.score,app=short(common,0),
                           mode=short(common,10),counters_hex=common[0x130:0x170].hex())
                last_common=common
                if result_state!=last_result:
                    if diagnostics:
                        record('result_state_raw',perf_counter_ns=end,dialog_latch=short(result_state[0],0),
                               completion_record_hex=result_state[1].hex(),score=self.score)
                    if context and last_result is not None and short(result_state[0],0)==-1 and short(last_result[0],0)!=-1:
                        retry=True
                        round_started=False
                        self._say(f'Try again. Score {self.score}.')
                        record('retry_dialog_entered',score=self.score)
                    elif short(result_state[0],0)!=-1:retry=False
                    last_result=result_state
                self.retry_active=retry and context
                if self.handoff_observe or self.handoff_sound:
                    handoff,sample=self.handoff.poll(a,context_key,active=not (retry or self.diagnostic_paused))
                    if self.handoff_observe and sample is not None:
                        identity=(sample['native'],sample['target'])
                        if identity!=last_handoff_sample:
                            record('handoff_frame_sample',**sample);last_handoff_sample=identity
                    if handoff:
                        record('handoff_visible',**handoff)
                        if self.handoff_sound:
                            record('handoff_submission',**handoff,**self.cues.play_handoff())
                rating_active=bool(context and short(a,0x8a)>0 and not retry)
                rating_change=self.rating_changes.poll(a,stage=context_key,active=rating_active)
                if rating_change:
                    self._say(rating_announcement(rating_change,self.rating_changes.changed_from))
                    record('rating_changed',rating=rating_change,raw=short(a,0x4e),stage=context_key)
                # On Cool the player freestyles, so the teacher's note cues stay silent.
                freestyle=freestyle_active(a,active=rating_active)
                if end-last_card_poll>20_000_000:
                    last_card_poll=end
                    if self.all_cool:
                        patched=apply_all_cool(self.ram,getattr(self.menu,'_screen',None)=='stage')
                        if patched:record('all_cool_reapplied',targets=patched,stage=context_key)
                    subtitle=self.subtitles.poll()
                    if subtitle:
                        text,kind=subtitle
                        reason=suppression_reason(kind,self.subtitles_enabled,self.lyrics_enabled)
                        if reason is None:
                            # Dialogue lines queue behind each other; nothing is cut off.
                            self._say(text,interrupt=False);record('subtitle_speech',text=text,kind=kind,pointer=self.subtitles.pointer,stage=context_key)
                        else:record('subtitle_suppressed',text=text,kind=kind,reason=reason,stage=context_key)
                    self.card_context.modal=None
                    self.card_context.scene=None
                    self.card_context.practice=False
                    self.card_context.practice_wait=None
                    self.card_context.title_selector=None
                    self.card_context.opening=False
                    observed=self.card_context.poll() if (practice_active or not context or short(a,0x8a)==0 or end-last_change>150_000_000) else None
                    if self.card_context.opening:
                        if not opening_active:
                            self.menu.reset();self._say('Opening scene.')
                            record('opening_context',active=True)
                        opening_active=True;opening_seen=end
                    elif opening_active and end-opening_seen>250_000_000:
                        opening_active=False;record('opening_context',active=False)
                    title=self.card_context.title_selector
                    if title is not None:
                        if not title_active or self.menu._title_selector_address!=title:
                            self.menu.reset();self.menu.set_title_context(title)
                            record('title_context',selector_address=title)
                        title_active=True;title_seen=end
                    elif title_active and end-title_seen>250_000_000:
                        title_active=False
                    if self.card_context.practice:
                        if not practice_active:
                            self.menu.reset();record('practice_context',active=True)
                        practice_active=True;practice_seen=end
                    elif practice_active and end-practice_seen>250_000_000:
                        practice_active=False;self.practice.reset();self.menu.reset()
                        last_practice_state=None;record('practice_context',active=False)
                    scene=self.card_context.scene
                    if scene is not None and scene!=announced_card_scene:
                        self.last_scene=scene
                        from duckstation_scene_speech import SCENE_TEXT
                        self._say(SCENE_TEXT[scene]);record('scene_speech',stage=min(scene,6),
                            scene='ending' if scene==7 else 'intro',text=SCENE_TEXT[scene])
                        announced_card_scene=scene
                    elif round_started:
                        announced_card_scene=None
                    if self.card_context.modal==(6,0x80049278):
                        if not highscores_active:
                            message=self.menu._read_highscores()
                            if message:
                                self._say(message);record('menu_speech',text=message,hint='X Exit.')
                                highscores_active=True
                        highscores_seen=end
                    elif highscores_active and end-highscores_seen>250_000_000:
                        highscores_active=False;self.menu.reset()
                    if observed is not None:
                        if active_card!=observed:
                            self.menu.reset();record('card_context',mode=observed[0],state_pointer=observed[1])
                        active_card=observed;card_seen=end
                    elif active_card is not None and end-card_seen>250_000_000:
                        active_card=None;self.cards.reset();self.menu.reset();record('card_context',mode=None)
                menu_allowed=not replay_active and (practice_active or highscores_active or active_card is not None or not context or (short(a,0x8a)==0 and a==previous and end-last_change>150_000_000))
                pid=ctypes.c_ulong();self.u.GetWindowThreadProcessId(self.u.GetForegroundWindow(),ctypes.byref(pid))
                down=pid.value==self.pid and bool(self.u.GetAsyncKeyState(SCORE_VK)&0x8000)
                if down and not ekey:self._say(f'Score {self.score}.');record('score_requested',score=self.score)
                ekey=down
                down=pid.value==self.pid and bool(self.u.GetAsyncKeyState(RATING_VK)&0x8000)
                if down and not fkey:
                    rating=rating_name(a,active=rating_active)
                    if rating:
                        self._say(rating_announcement(rating));record('rating_requested',rating=rating,raw=short(a,0x4e),stage=context_key)
                fkey=down
                down=pid.value==self.pid and bool(self.u.GetAsyncKeyState(LYRICS_VK)&0x8000)
                if down and not ykey:
                    self.lyrics_enabled=not self.lyrics_enabled
                    self._say('Lyrics on.' if self.lyrics_enabled else 'Lyrics off.');record('lyrics_toggled',enabled=self.lyrics_enabled)
                    self._remember(lyrics=self.lyrics_enabled)
                ykey=down
                down=pid.value==self.pid and bool(self.u.GetAsyncKeyState(SUBTITLES_VK)&0x8000)
                if down and not ukey:
                    self.subtitles_enabled=not self.subtitles_enabled
                    self._say('Subtitles on.' if self.subtitles_enabled else 'Subtitles off.');record('subtitles_toggled',enabled=self.subtitles_enabled)
                    self._remember(subtitles=self.subtitles_enabled)
                ukey=down
                down=pid.value==self.pid and bool(self.u.GetAsyncKeyState(HINT_VK)&0x8000)
                hint_pressed=down and not hkey
                hkey=down
                if menu_allowed and (hint_pressed or end-last_menu>50_000_000):
                    last_menu=end
                    if bounded:
                        menu_raw={hex(address):self.ram.read(address,size).hex() for address,size in
                                  ((0x800544f8,0x40),(0x80049244,0x48),(0x80087b78,0x30),
                                   (0x8006ecf0,0x20),(0x8007cc50,0x30),(0x80048e50,0x30))}
                        if menu_raw!=last_menu_raw:
                            record('menu_state_raw',perf_counter_ns=end,regions=menu_raw)
                            last_menu_raw=menu_raw
                        if getattr(self.ram,'registers_address',None) is not None:
                            registers=self.ram.read_registers()
                            stack=word(registers,29*4)
                            record('menu_registers',pc=self.ram.read_program_counter(),registers_hex=registers.hex(),stack_address=stack,
                                   stack_hex=self.ram.read(stack,min(256,0x80200000-stack)).hex()
                                   if 0x80000000<=stack<0x80200000 else None)
                    reader=self.practice if practice_active else self.cards if active_card is not None else self.menu
                    if practice_active:
                        if diagnostics and a!=last_practice_state:
                            record('practice_state',state_hex=a.hex());last_practice_state=a
                        messages=self.practice.poll(a,True)
                        # The speech backend interrupts prior utterances. Keep
                        # an entry heading and its first panel together.
                        if messages:messages=[' '.join(messages)]
                    else:
                        messages=[] if highscores_active else self.cards.poll(active_card) if active_card is not None else self.menu.poll()
                    for message in messages:
                        self._say(message);record('menu_speech',text=message,hint=reader.hint())
                if hint_pressed and retry and not replay_active:self._say('X Retry. Circle Main menu.')
                elif hint_pressed and menu_allowed:
                    hint='' if opening_active else self.practice.hint() if practice_active else 'X Exit.' if highscores_active else (self.cards if active_card is not None else self.menu).hint()
                    if hint:self._say(hint)
                tick=word(a,0xc)
                if self.campaign and not self.diagnostic_paused:
                    active=bool(context and round_started and not retry and 192<=tick<1_000_000)
                    for event in self.campaign.poll(context_key or 1,tick,word(a,0x18),active):
                        kind=event.pop('event');record('campaign_'+kind,**event)
                if self.developer and not self.diagnostic_paused:
                    driver_valid=context_key==1 and 192<=tick<1_000_000
                    if driver_valid or developer_started:
                        developer_started=True
                        driver_valid=driver_valid and not (a==previous and end-last_change>150_000_000)
                        for event in self.developer.poll(tick,word(a,0x18),driver_valid):
                            kind=event.pop('event');record('developer_'+kind,**event)
                if context:
                    if previous is None:previous=a;last_tick=tick;last_change=end
                    if a!=previous:
                        last_change=end
                        if paused:record('state_resumed');paused=False;previous=a
                        if tick!=last_tick:
                            ticks+=1
                            if diagnostics:
                                record('game_update',perf_counter_ns=end,tick=tick,previous_tick=last_tick,
                                       observation_gap_ns=gap,read_started_ns=before,state_hex=a.hex())
                            if last_tick is not None and ((tick-last_tick)&0xffffffff)>192:
                                record('clock_discontinuity',previous_tick=last_tick,tick=tick)
                                if completed_scene_reset(round_started,last_tick,tick,retry):
                                    self._say(f'Score {self.score}.')
                                    record('round_score',stage=context_key,score=self.score,reason='scene_clock_reset')
                                    self.completed_stages[context_key]=self.score
                                    round_started=False
                                previous=a;self.cues.stop()
                            last_tick=tick
                        pad=word(a,0x18)
                        if diagnostics and pad!=last_pad:
                            record('game_pad_change',perf_counter_ns=end,tick=tick,mask=pad,
                                   previous_mask=last_pad,lane=word(a,0x20),input_tick=word(a,0x10),
                                   history_hex=self.ram.read(0x8008eefc,128).hex(),
                                   score=self.score,observation_gap_ns=gap)
                            last_pad=pad
                        input_tick=word(a,0x10)
                        if diagnostics and input_tick!=last_input_tick:
                            rows={}
                            for offset in (0x40,0x44):
                                pointer=word(a,offset)
                                if 0x80000000<=pointer<=0x801fffe8:
                                    rows[hex(offset)]=dict(pointer=pointer,bytes=self.ram.read(pointer,24).hex())
                            record('input_accounting_change',perf_counter_ns=end,tick=tick,input_tick=input_tick,
                                   mask=pad,lane=word(a,0x20),rows=rows,score=self.score,
                                   history_hex=self.ram.read(0x8008eefc,128).hex())
                            last_input_tick=input_tick
                        for event in profile_events(previous,a,self.grid,profile):
                            record('cursor_consumed',perf_counter_ns=end,**event)
                            if 'rejected' in event:continue
                            round_started=True
                            if event['cursor'].startswith('primary'):
                                reason=cue_suppression_reason(profile,gap,freestyle)
                                if reason=='poll_gap':
                                    record('cue_suppressed',reason=reason,gap_ns=gap,**event)
                                elif reason:
                                    record('cue_suppressed',reason=reason,**event)
                                else:
                                    result=self.cues.play(event['button'])
                                    record('cue_submission',detected_ns=end,**event,**result)
                                    cue_count+=1
                        previous=a
                    elif end-last_change>150_000_000 and not paused:
                        self.cues.stop();paused=True;record('state_stalled',tick=tick)
                # Python 3.11+ sleep uses a Windows high-resolution waitable timer;
                # Event.wait(.002) measured ~15.7 ms on this machine.
                time.sleep(.002)
        except Exception as exc:
            if not self.stop_event.is_set() and self.ram.ram_available():
                self.error=str(exc)
                record('monitor_error',message=self.error)
                self._say('Timing observer stopped.' if not diagnostics else 'Timing observer stopped. See the diagnostics log.')
            else:record('emulator_closed')
        finally:
            if self.campaign:
                for event in self.campaign.close():
                    kind=event.pop('event');record('campaign_'+kind,**event)
            if self.developer:
                for event in self.developer.close():
                    kind=event.pop('event');record('developer_'+kind,**event)
            self.cues.stop();self.capture.set_armed(False)
            if bounded:self.summary=summary();record('monitor_summary',**self.summary)

    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(3)
        if getattr(self,'speech_thread',None):self.speech_thread.join(1)
        self.cues.stop()
