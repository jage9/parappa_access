-- Explicit developer-only controller test. Never loaded by the spoken launcher.
-- Reads cursor events; presses ordinary PS1 buttons. No game RAM/code edits.
-- Configure developerPlayConfig = {stage=N, statePath='../../logs/...sstate'}.
local config=assert(developerPlayConfig,'Explicit developer configuration required')
assert(type(config.statePath)=='string' and config.statePath:match('^%.%./%.%./logs/') and not config.statePath:sub(12):find('%.%.'),'Use an ignored logs checkpoint')
local maxAttempts=config.maxAttempts or 8
assert(maxAttempts>=1 and maxAttempts<=12,'Attempts outside 1..12')
local offset=config.offsetTicks or -6
assert(offset>=-24 and offset<=24,'Offset outside -24..24')
local ffi=require('ffi');local ram=PCSX.getMemPtr()
local function word(a)return tonumber(ffi.cast('uint32_t*',ram+a-0x80000000)[0])end
local function short(a)return tonumber(ffi.cast('int16_t*',ram+a-0x80000000)[0])end
local profile=assert(Support.extra.dofile('../../scripts/stage-profiles.lua')[config.stage],'Unknown stage')
local cache=config.seed or {};local known={}
for _,n in ipairs(cache)do known[n[1]]=true end
local schedule={};local names={'TRIANGLE','CIRCLE','CROSS','SQUARE','L1','L1','R1','R1'}
local pad=PCSX.SIO0.slots[1].pads[1];local b=PCSX.CONSTS.PAD.BUTTON
local trial,frame,nextNote,release=0,0,1,0;local held;local loading=true
local previousMono=PCSX.settings.spu.Mono
developerPlayRefs={};local refs=developerPlayRefs
local function releaseAll()for _,name in ipairs(names)do pad.clearOverride(b[name])end;held=nil end
local function nextTrial()
 releaseAll();trial=trial+1
 if trial>maxAttempts then PCSX.log('BOT_STOP attempts='..maxAttempts..'\n');PCSX.quit(0);return end
 PCSX.pauseEmulator()
 local f=Support.File.open(config.statePath);assert(not f:failed(),'Checkpoint unavailable');PCSX.loadSaveState(f);f:close()
 assert(word(profile.entry)==0x27bdffc8 and word(profile.loop)==(profile.loopWord or 0x27bdffd0) and
  word(0x800943d0)==profile.grid and word(0x800943d4)==profile.count,'Checkpoint profile mismatch')
 table.sort(cache,function(a,b)return a[1]<b[1]end);schedule={};for _,n in ipairs(cache)do schedule[#schedule+1]=n end
 frame=0;nextNote=1;loading=false;PCSX.settings.spu.Mono=true
 PCSX.log(string.format('BOT_START stage=%d trial=%d known=%d offset=%d\n',profile.stage,trial,#schedule,offset));PCSX.resumeEmulator()
end
local function runTrial()
 local ok,err=pcall(nextTrial)
 if not ok then
  loading=true;releaseAll();PCSX.log('BOT_START_FAILED '..tostring(err)..'\n');PCSX.quit(2)
 end
end
local counts={PRIMARY=0,RESPONSE=0}
local specs={{profile.primary[1],'PRIMARY',0x94,0x8c,0x90,1,1},{profile.primary[2],'PRIMARY',0x94,0x8c,0x90,1,2},{profile.primary[3],'PRIMARY',0x98,0x8e,0x90,2,2},{profile.response[1],'RESPONSE',0xa4,0x9e,0xa2,1,1},{profile.response[2],'RESPONSE',0xa4,0x9e,0xa2,1,2},{profile.response[3],'RESPONSE',0xa8,0xa0,0xa2,2,2}}
for _,site in ipairs(specs)do local spec=site
 refs[#refs+1]=PCSX.addBreakpoint(spec[1],'Exec',4,'Strict stage cursor verification',function()
  if loading then return end
  local ok,err=pcall(function()
   local r=PCSX.getRegisters().GPR.n;local state=tonumber(r.s1)
   assert(state==0x801c3640 and word(0x800943d0)==profile.grid and word(0x800943d4)==profile.count,'Context')
   assert(bit.band(word(state),8)~=0 and short(state+0x8a)==spec[7] and short(state+spec[5])==spec[6],'Gate')
   local ptr=word(state+spec[3]);local off=ptr-profile.grid;local index=short(state+spec[4])
   assert(off>=0 and off<profile.count*44 and (off%44==4 or off%44==24) and index>=0 and index<19,'Grid')
   assert(tonumber(r.v0)==ptr+index,'Cursor')
   local lane=tonumber(ram[ptr+index-0x80000000]);assert(lane==0 or lane==255 or names[lane],'Button')
   if names[lane]then counts[spec[2]]=counts[spec[2]]+1 end
  end)
  if not ok then PCSX.log('BOT_GATE_FAILED '..tostring(err)..'\n');releaseAll();loading=true;PCSX.nextTick(function()PCSX.quit(2)end)end
 end)
end
for _,address in ipairs(profile.response) do
 refs[#refs+1]=PCSX.addBreakpoint(address,'Exec',4,'Developer observe response',function()
  if loading or word(0x800943d0)~=profile.grid then return end
  local r=PCSX.getRegisters().GPR.n;local a=tonumber(r.v0)
  if tonumber(r.s1)~=0x801c3640 or a<profile.grid or a>=profile.grid+profile.count*44 then return end
  local lane=tonumber(ram[a-0x80000000]);if not names[lane]then return end
  local target=math.floor(word(0x801c364c)/24)*24
  PCSX.log(string.format('BOT_RESPONSE tick=%d lane=%d\n',target,lane))
  if not known[target]then known[target]=true;cache[#cache+1]={target,lane}end
 end)
end
refs.input=PCSX.addBreakpoint((profile.entry+0x484),'Exec',4,'Developer controller receive',function()
 if not loading and held and tonumber(PCSX.getRegisters().GPR.n.v0)~=0 then releaseAll()end
end)
refs.result=PCSX.addBreakpoint(profile.result,'Exec',4,'Developer stage result',function()
 if loading or word(0x800943d0)~=profile.grid or word(profile.result)~=(profile.resultWord or 0x3c128009) then return end
 local result=tonumber(PCSX.getRegisters().GPR.n.v0)
 PCSX.log(string.format('BOT_RESULT trial=%d result=%d score=%d known=%d\n',trial,result,short(0x80091816),#cache))
 PCSX.log(string.format('BOT_VERIFIED primary=%d response=%d\n',counts.PRIMARY,counts.RESPONSE))
 loading=true;releaseAll()
 if result==1 then
  PCSX.nextTick(function()
   local path='../../logs/bot-stage'..profile.stage..'-clear-'..os.date('!%Y%m%dT%H%M%SZ')..'.sstate'
   assert(not io.open(path,'rb'),'Checkpoint already exists')
   local f=Support.File.open(path,'TRUNCATE');f:writeMoveSlice(PCSX.createSaveState());f:close()
   PCSX.log('BOT_CLEAR_CHECKPOINT '..path..'\n');PCSX.quit(0)
  end)
 else PCSX.nextTick(runTrial)end
end)
refs.vsync=PCSX.Events.createEventListener('GPU::Vsync',function()
 if loading then return end
 frame=frame+1;if held and frame>=release then releaseAll()end
 local n=schedule[nextNote];local tick=word(0x801c364c)
 if n and tick<1000000 and tick>=n[1]+offset then
  releaseAll();held=names[n[2]];pad.setOverride(b[held]);release=frame+6;nextNote=nextNote+1
 end
 if frame==18000 then PCSX.log('BOT_TIMEOUT\n');releaseAll();PCSX.quit(2)end
end)
refs.quit=PCSX.Events.createEventListener('Quitting',function()releaseAll();PCSX.settings.spu.Mono=previousMono end)
PCSX.nextTick(runTrial)
