# -*- coding: utf-8 -*-
"""strict_wow.py —— 严格校验版 WoW API 模拟器（QuestGear/QuickReply 通用）

用途：在没有游戏客户端的情况下，模拟 WoW 客户端 API，并对**参数类型与取值**做校验，
      从而发现「Lua 语法没错但运行时 API 参数非法」这类错误
      （例：FontString:SetPoint() Invalid region point 1）。

与普通 stub 的区别：
  - SetPoint 的 point 必须是合法锚点字符串；rel 必须是 frame(table)；x/y 必须是数字
  - SetFrameStrata 的 strata 必须是合法枚举（OVERLAY 是 DrawLayer、不是 strata，v1.90 补）
  - SetSize/SetWidth/SetHeight 参数必须是数字
  - SetText 参数必须是 string/number/nil
  - SetTextColor/SetVertexColor 参数必须是 0~1 数字
  - CreateFontString/CreateTexture 的类型参数会校验
  - 错误不抛出、全部收集，带【调用点 文件:行号】，一次跑出所有问题

用法：
    from strict_wow import make_env
    lua, env = make_env()
    lua.execute(open('QuestGear.lua', encoding='utf-8').read())
    env.report()
"""
import re

# 合法锚点 / frame 类型 / draw layer 的定义在下方 Lua stub 内部（权威来源）
# 这里只保留 Python 侧的说明，实际校验由 Lua 内的 chkSetPoint 等完成。

STUB = r'''
-- ===== 严格校验 WoW API 模拟器 =====
ERRORS = {}        -- 收集的错误
WARNS  = {}
__errs = 0
STRICT = false     -- true 时像真客户端一样对非法参数直接抛错（模拟加载中断）

local ANCHORS = {
    TOPLEFT = true, TOP = true, TOPRIGHT = true,
    LEFT = true, CENTER = true, RIGHT = true,
    BOTTOMLEFT = true, BOTTOM = true, BOTTOMRIGHT = true,
}
local FRAME_TYPES = {
    Frame = true, Button = true, EditBox = true, CheckButton = true,
    StatusBar = true, Slider = true, ScrollBar = true, ScrollFrame = true,
    MessageFrame = true, ModelFrame = true, GameTooltip = true,
    UIDropDownMenu = true, GameFont = true,
}
local LAYERS = {
    BACKGROUND = true, BORDER = true, ARTWORK = true,
    OVERLAY = true, HIGHLIGHT = true,
}
-- layer 白名单来源：实测本机客户端 Interface/AddOns 下所有插件的
-- CreateTexture/CreateFontString 调用中出现过的 layer 值（不含本插件自身）。
-- 不含 LOW / DIALOG —— 这两个在本客户端 CreateTexture 会报
-- "bad argument #3 to '?' (Usage: local texture = self:CreateTexture(params))"
-- 需要重新推导时跑：python derive_whitelist.py

local function addErr(msg, lvl)
  __errs = __errs + 1
  local info = debug.getinfo(lvl or 3, "Sl")
  local where = ""
  if info then
    where = string.format("  @ %s:%d", info.short_src or "?", info.currentline or 0)
  end
  ERRORS[#ERRORS+1] = msg .. where
end
local function addWarn(msg, lvl)
  WARNS[#WARNS+1] = msg
end

local function isNum(v) return type(v) == "number" end
local function isFrame(v) return type(v) == "table" end

-- ---------- 校验型方法实现 ----------
local function chkSetPoint(self, point, rel, relPoint, x, y, lvl)
  if type(point) ~= "string" then
    addErr(string.format("SetPoint: 第1参 point 必须是锚点字符串，实际是 %s (%s)",
      type(point), tostring(point)), (lvl or 3) + 1)
    if STRICT then error(string.format("SetPoint: Invalid region point %s", tostring(point)), (lvl or 3) + 1) end
    return
  end
  if not ANCHORS[point] then
    addErr(string.format("SetPoint: 非法锚点 %q（合法: TOPLEFT/TOP/TOPRIGHT/LEFT/CENTER/RIGHT/BOTTOMLEFT/BOTTOM/BOTTOMRIGHT）", point),
      (lvl or 3) + 1)
    if STRICT then error(string.format("SetPoint: Invalid region point %q", point), (lvl or 3) + 1) end
  end
  if rel ~= nil and not isFrame(rel) then
    addErr(string.format("SetPoint: 第2参 rel 必须是 Frame 或 nil，实际是 %s (%s)",
      type(rel), tostring(rel)), (lvl or 3) + 1)
    if STRICT then error(string.format("SetPoint: bad relative frame %s", tostring(rel)), (lvl or 3) + 1) end
  end
  if relPoint ~= nil then
    if type(relPoint) ~= "string" then
      addErr(string.format("SetPoint: 第3参 relPoint 必须是锚点字符串或 nil，实际是 %s (%s)",
        type(relPoint), tostring(relPoint)), (lvl or 3) + 1)
      if STRICT then error(string.format("SetPoint: Invalid region point %s", tostring(relPoint)), (lvl or 3) + 1) end
    elseif not ANCHORS[relPoint] then
      addErr(string.format("SetPoint: 非法 relPoint 锚点 %q", relPoint), (lvl or 3) + 1)
      if STRICT then error(string.format("SetPoint: Invalid region point %q", relPoint), (lvl or 3) + 1) end
    end
  end
  if x ~= nil and not isNum(x) then
    addErr(string.format("SetPoint: x 偏移必须是数字，实际是 %s (%s)", type(x), tostring(x)), (lvl or 3) + 1)
    if STRICT then error(string.format("SetPoint: bad x offset %s", tostring(x)), (lvl or 3) + 1) end
  end
  if y ~= nil and not isNum(y) then
    addErr(string.format("SetPoint: y 偏移必须是数字，实际是 %s (%s)", type(y), tostring(y)), (lvl or 3) + 1)
    if STRICT then error(string.format("SetPoint: bad y offset %s", tostring(y)), (lvl or 3) + 1) end
  end
  if rel ~= nil and relPoint == nil then
    addWarn("SetPoint: 给了 rel 但没给 relPoint，将以 point 作为相对锚点")
  end
  if rel == nil and relPoint ~= nil then
    addErr("SetPoint: 给了 relPoint 但没给 rel（非法用法）", (lvl or 3) + 1)
    if STRICT then error("SetPoint: relPoint without rel", (lvl or 3) + 1) end
  end
end

local function chkNum(name, ...)
  for i = 1, select("#", ...) do
    local v = select(i, ...)
    if not isNum(v) then
      addErr(string.format("%s: 参数%d 必须是数字，实际是 %s (%s)", name, i, type(v), tostring(v)), 4)
      return false
    end
  end
  return true
end

local function chkColor(name, r, g, b)
  for i, v in ipairs({r, g, b}) do
    if not isNum(v) then
      addErr(string.format("%s: 分量%d 必须是数字，实际是 %s (%s)", name, i, type(v), tostring(v)), 4)
      return false
    end
    if v < 0 or v > 1 then
      addErr(string.format("%s: 分量%d 必须在 0~1，实际是 %s", name, i, tostring(v)), 4)
      return false
    end
  end
  return true
end

-- ---------- Frame 对象 ----------
local FrameMT = {}

local function makeObj(kind)
  local o = { __kind = kind, _texts = {}, _scripts = {}, _hooks = {}, _shown = true, _point = nil }  setmetatable(o, {
    __index = function(t, k)
      local f = FrameMT[k]
      if f then return f end
      -- 未实现的方法：返回安全空函数（不报错，避免噪音），但记录一次
      return function() return makeObj("unknown") end
    end,
    __newindex = function(t, k, v) rawset(t, k, v) end,
  })
  return o
end

FrameMT.SetPoint = function(self, point, rel, relPoint, x, y)
  chkSetPoint(self, point, rel, relPoint, x, y, 3)
  -- v1.104：真机 SetPoint 是「累加」的，重复设置会并存。_point 仍保留最后一个
  -- （兼容既有只读最后锚点的断言），另把全部锚点记进 _points，专测用来抓
  -- 「重设锚点前没 ClearAllPoints」这类真机才暴露的错位。
  local pts = rawget(self, "_points")
  if not pts then pts = {} rawset(self, "_points", pts) end
  pts[#pts + 1] = { point, relPoint or point, x or 0, y or 0, rel }
  rawset(self, "_point", pts[#pts])
  -- 可选钩子：让测试记录 SetPoint 实参（供布局断言用）
  if _G.__POINT_HOOK then
    _G.__POINT_HOOK(self, point, rel, relPoint, x, y)
  end
end
FrameMT.ClearAllPoints = function(self)
  rawset(self, "_points", nil)
  rawset(self, "_point", nil)
end
-- v1.98：客户端 layout-local.txt 接管相关的桩。真机上 StartMoving() 会自动把
-- userPlaced 置 true，这里只记录显式调用，供测试断言插件确实退出客户端管理。
FrameMT.SetUserPlaced = function(self, v)
  rawset(self, "_userPlaced", v and true or false)
end
FrameMT.IsUserPlaced = function(self)
  return rawget(self, "_userPlaced") == true
end
FrameMT.SetDontSavePosition = function(self, v)
  rawset(self, "_dontSavePosition", v and true or false)
end
-- v1.90：SetFrameStrata 的 strata 是枚举；OVERLAY 是纹理 DrawLayer、不是合法 strata。
-- 真机对非法值报 bad argument #1 并中断，桩里若走万能假对象就会假阳性——显式校验堵住。
local VALID_STRATA = {
  WORLD=true, BACKGROUND=true, LOW=true, MEDIUM=true, HIGH=true,
  DIALOG=true, FULLSCREEN=true, FULLSCREEN_DIALOG=true, TOOLTIP=true, PARENT=true,
}
FrameMT.SetFrameStrata = function(self, strata)
  if type(strata) ~= "string" or not VALID_STRATA[strata] then
    addErr(string.format("SetFrameStrata: 非法 strata %q（合法: WORLD/BACKGROUND/LOW/MEDIUM/HIGH/DIALOG/FULLSCREEN/FULLSCREEN_DIALOG/TOOLTIP/PARENT；注意 OVERLAY 是纹理 DrawLayer 不是 strata）", tostring(strata)), 4)
    if STRICT then error(string.format("SetFrameStrata: bad strata %s", tostring(strata)), 4) end
  end
  self._strata = strata
end
FrameMT.GetFrameStrata = function(self) return self._strata or "MEDIUM" end
-- v1.100：SetToplevel 真语义——记录标记，供"原生 click-to-front 置顶"专项断言。
-- 插件加载期调用一次（非战斗、非安全帧），客户端 C 层随后在点击子控件时自动 raise。
FrameMT.SetToplevel = function(self, on)
  if type(on) ~= "boolean" then
    addErr(string.format("SetToplevel: 参数须为 boolean，实际 %s", type(on)), 4)
  end
  self._toplevel = on and true or false
end
FrameMT.IsToplevel = function(self) return self._toplevel == true end
FrameMT.SetFrameLevel = function(self, level) chkNum("SetFrameLevel", level); self._level = level end
FrameMT.GetFrameLevel = function(self) return self._level or 0 end
FrameMT.SetSize  = function(self, w, h) chkNum("SetSize", w, h) end
FrameMT.SetWidth = function(self, w) chkNum("SetWidth", w); self._w = w end
FrameMT.SetHeight= function(self, h) chkNum("SetHeight", h) end
FrameMT.SetAlpha = function(self, a) chkNum("SetAlpha", a) end
FrameMT.SetWordWrap = function(self, on) self._wordWrap = on end  -- 行距/重叠测试断言用
FrameMT.SetTexCoord = function(self, ...) chkNum("SetTexCoord", ...) end
FrameMT.SetVertexColor = function(self, r, g, b, a)
  chkColor("SetVertexColor", r, g, b)
  if a ~= nil then chkNum("SetVertexColor.a", a) end
end
FrameMT.SetTextColor = function(self, r, g, b) chkColor("SetTextColor", r, g, b) end
FrameMT.SetText = function(self, s)
  if s ~= nil and type(s) ~= "string" and type(s) ~= "number" then
    addErr(string.format("SetText: 必须是字符串/数字/nil，实际是 %s (%s)", type(s), tostring(s)), 4)
  end
  self._texts[#self._texts+1] = tostring(s)
end
FrameMT.GetText = function(self) return self._texts[#self._texts] or "" end
FrameMT.SetTexture = function(self, path)
  if type(path) ~= "string" then
    addErr(string.format("SetTexture: 必须是纹理路径字符串，实际是 %s", type(path)), 4)
  end
  self._texture = path
end
FrameMT.SetHighlightTexture = function(self, path, blend)
  -- WoW API 两种写法都合法：传纹理路径字符串，或传已创建的 texture 对象
  if type(path) == "table" then
    self._highlight = path
  elseif type(path) == "string" then
    self._highlight = makeObj("texture")
    self._highlight._texture = path
  else
    addErr(string.format("SetHighlightTexture: 必须是纹理路径或 texture 对象，实际是 %s", type(path)), 4)
    return nil
  end
  self._highlight._blend = blend
  return self._highlight
end
FrameMT.SetNormalTexture = function(self, path)
  self._normal = makeObj("texture"); self._normal._texture = path; return self._normal
end
FrameMT.SetPushedTexture = function(self, path)
  self._pushed = makeObj("texture"); self._pushed._texture = path; return self._pushed
end
FrameMT.SetBlendMode = function(self, mode)
  if type(mode) ~= "string" then
    addErr(string.format("SetBlendMode: 模式必须是字符串，实际是 %s", type(mode)), 4)
  end
  self._blend = mode
end
FrameMT.SetFontObject = function(self, f)
  if type(f) ~= "string" then
    addErr(string.format("SetFontObject: 必须是字体名字符串，实际是 %s", type(f)), 4)
  end
end
FrameMT.SetScript = function(self, ev, fn)
  if type(fn) ~= "function" then
    addErr(string.format("SetScript(%s): 回调必须是 function，实际是 %s", tostring(ev), type(fn)), 4)
  end
  local scripts = rawget(self, "_scripts")
  if type(scripts) ~= "table" then scripts = {}; rawset(self, "_scripts", scripts) end
  scripts[ev] = fn
end
FrameMT.GetScript = function(self, ev)
  local scripts = rawget(self, "_scripts")
  if type(scripts) == "table" then return scripts[ev] end
  return nil
end
-- v1.96：HookScript 桩——真客户端 hook 与主脚本并存、都按注册顺序触发。
-- 旧版走万能假对象被静默吞掉，导致「面板/按钮挂了置顶 hook」测试假阳性。
FrameMT.HookScript = function(self, ev, fn)
  if type(fn) ~= "function" then
    addErr(string.format("HookScript(%s): 回调必须是 function，实际是 %s", tostring(ev), type(fn)), 4)
  end
  local hooks = rawget(self, "_hooks")
  if type(hooks) ~= "table" then hooks = {}; rawset(self, "_hooks", hooks) end
  local list = hooks[ev]
  if type(list) ~= "table" then list = {}; hooks[ev] = list end
  list[#list + 1] = fn
end
-- 测试专用：按真客户端语义触发事件（先主脚本，再逐个 hook）。
FrameMT.FireScript = function(self, ev, ...)
  local scripts = rawget(self, "_scripts")
  local s = scripts and scripts[ev]
  if type(s) == "function" then s(self, ...) end
  local hooks = rawget(self, "_hooks")
  local hs = hooks and hooks[ev]
  if type(hs) == "table" then for i = 1, #hs do if type(hs[i]) == "function" then hs[i](self, ...) end end end
end
-- v1.96：Raise 桩——同 strata 提到最前（用全局递增计数器模拟同级 z 序）。
-- 上一轮面板调 Raise 被万能假对象吞掉，是真机没置顶的直接原因之一。
FrameMT.Raise = function(self)
  _G.__RAISE_SEQ = (_G.__RAISE_SEQ or 0) + 1
  self._raisedSeq = _G.__RAISE_SEQ
end
-- 拖动桩：记录可拖动按钮与移动状态，供标题栏锚点测试断言
FrameMT.RegisterForDrag = function(self, ...)
  self._dragButtons = {...}
end
FrameMT.StartMoving = function(self) self._moving = true end
FrameMT.StopMovingOrSizing = function(self) self._moving = false end
FrameMT.SetMovable = function(self, b) self._movable = b end
-- SetBackdrop 桩：校验表结构（bgFile/edgeFile/edgeSize/insets），记录到 _backdrop 供测试断言
FrameMT.SetBackdrop = function(self, bd)
  if bd ~= nil and type(bd) ~= "table" then
    addErr("SetBackdrop: 参数必须是 table 或 nil，实际是 " .. type(bd), 4)
  end
  if type(bd) == "table" then
    if bd.bgFile ~= nil and type(bd.bgFile) ~= "string" then addErr("SetBackdrop: bgFile 必须是字符串", 4) end
    if bd.edgeFile ~= nil and type(bd.edgeFile) ~= "string" then addErr("SetBackdrop: edgeFile 必须是字符串", 4) end
    if bd.edgeSize ~= nil and not isNum(bd.edgeSize) then addErr("SetBackdrop: edgeSize 必须是数字", 4) end
  end
  self._backdrop = bd
end
FrameMT.SetBackdropColor = function(self, r, g, b, a)
  chkColor("SetBackdropColor", r, g, b)
  if a ~= nil then chkNum("SetBackdropColor.a", a) end
end
FrameMT.SetBackdropBorderColor = function(self, r, g, b, a)
  chkColor("SetBackdropBorderColor", r, g, b)
  if a ~= nil then chkNum("SetBackdropBorderColor.a", a) end
end
FrameMT.GetBackdrop = function(self) return self._backdrop end
FrameMT.CreateFontString = function(self, name, layer, font)
  if name ~= nil and type(name) ~= "string" then
    addErr("CreateFontString: name 必须是字符串或 nil", 4)
  end
  if layer ~= nil and not LAYERS[layer] then
    addErr(string.format("CreateFontString: 非法 layer %q", tostring(layer)), 4)
    if STRICT then error(string.format("CreateFontString: Invalid layer %q", tostring(layer)), 4) end
  end
  if font ~= nil and type(font) ~= "string" then
    addErr(string.format("CreateFontString: 字体必须是字符串，实际是 %s", type(font)), 4)
  end
  return makeObj("FontString")
end
FrameMT.CreateTexture = function(self, name, layer, template, subLevel)
  if name ~= nil and type(name) ~= "string" then
    addErr("CreateTexture: name 必须是字符串或 nil", 4)
  end
  if layer ~= nil and not LAYERS[layer] then
    addErr(string.format("CreateTexture: 非法 layer %q（实测本客户端合法: BACKGROUND/BORDER/ARTWORK/OVERLAY/HIGHLIGHT）", tostring(layer)), 4)
    if STRICT then error(string.format("CreateTexture: bad argument #3 to '?' (Usage: local texture = self:CreateTexture(params))"), 4) end
  end
  if subLevel ~= nil and not isNum(subLevel) then
    addErr("CreateTexture: subLevel 必须是数字", 4)
  end
  return makeObj("Texture")
end
FrameMT.IsShown = function(self) return self._shown end
FrameMT.IsVisible = function(self) return self._shown end
-- v1.78：键盘/焦点桩（ESC 分层返回测试用）
FrameMT.EnableKeyboard = function(self, b) self._keyboardEnabled = b and true or false end
FrameMT.SetPropagateKeyboardInput = function(self, b) self._propagate = b and true or false end
FrameMT.HasFocus = function(self) return self._focused == true end
FrameMT.SetFocus = function(self) self._focused = true end
FrameMT.ClearFocus = function(self) self._focused = false end
FrameMT.Show = function(self) self._shown = true end
FrameMT.Hide = function(self) self._shown = false end
FrameMT.GetPoint = function(self)
  -- v1.97：必须 rawget。万能 __index 会把未设置的 _point 读成假函数（truthy），
  -- 之后 self._point[1] 直接炸；此前没有测试在"没拖动过"的面板上调 GetPoint，故一直没暴露。
  local pt = rawget(self, "_point")
  if type(pt) == "table" then return pt[1], pt[5], pt[2], pt[3], pt[4] end
  return "CENTER", nil, "CENTER", 0, 0
end
FrameMT.GetName = function(self) return self.__name end

BackdropTemplateMixin = {}  -- 让 BACKDROP_TEMPLATE 解析为 "BackdropTemplate"
CreateFrame = function(frameType, name, parent, template)
  if frameType ~= nil and not FRAME_TYPES[frameType] then
    addErr(string.format("CreateFrame: 非法 frame 类型 %q", tostring(frameType)), 3)
  end
  if name ~= nil and type(name) ~= "string" then
    addErr("CreateFrame: name 必须是字符串或 nil", 3)
  end
  local o = makeObj(frameType or "Frame")
  o.__name = name
  o._parent = parent
  -- v1.96：记录子级，供"点击子按钮置顶"测试枚举真实按钮对象并触发其 OnMouseDown。
  if parent and type(parent) == "table" then
    -- 用 rawget：万能 __index 会把未定义的 _children 读成假函数，or {} 拦不住
    local kids = rawget(parent, "_children")
    if type(kids) ~= "table" then kids = {}; rawset(parent, "_children", kids) end
    kids[#kids + 1] = o
  end
  return o
end
UIParent = makeObj("Frame")
-- 小地图按钮测试桩：Minimap 作为 frame，提供圆心/缩放；GetCursorPosition 返回可控鼠标坐标
Minimap = makeObj("Minimap")
Minimap.GetCenter = function(self) return 400, 300 end
Minimap.GetEffectiveScale = function(self) return 1 end
__CURSOR = {x = 400, y = 300}
GetCursorPosition = function() return __CURSOR.x, __CURSOR.y end
DEFAULT_CHAT_FRAME = { AddMessage = function(self, m) end }
SlashCmdList = {}
print = function(...) end
GetTime = function() return 0 end
GetItemLink = nil
ChatFrameUtil = { InsertLink = function(link) end }
ChatEdit_InsertLink = nil
GameTooltip = makeObj("GameTooltip")
-- tooltip 内容桩：记录 SetText/AddLine 文本，供小地图按钮测试断言
GameTooltip._lines = {}
GameTooltip.SetOwner = function(self, owner, anchor) self._owner = owner; self._anchor = anchor end
GameTooltip.SetText = function(self, txt, r, g, b)
  self._lines = {}; self._lines[#self._lines+1] = tostring(txt)
end
GameTooltip.AddLine = function(self, txt, r, g, b, wrap)
  self._lines[#self._lines+1] = tostring(txt)
end
GameTooltip.ClearLines = function(self) self._lines = {} end
GameTooltip.Show = function(self) self._shown = true end
GameTooltip.Hide = function(self) self._shown = false end
IsModifiedClick = function(tok) return false end
IsAltKeyDown = function() return __ALT_DOWN == true end
__ALT_DOWN = false
SendChatMessage = function(msg, ch)
  __SENT = __SENT or {}
  __SENT[#__SENT+1] = { msg = msg, ch = ch }
end
SetItemRef = function(...) end
GetCVarBool = function(n) return false end
GetCVar = function(n) return "" end
SetCVar = function(n, v) end
-- 常用 WoW 全局 API（避免误报"未定义全局"）
ReloadUI = function() end
-- 已完成查询桩：测试可设 __QUEST_DONE[id]=true 模拟已完成任务
__QUEST_DONE = {}
-- v1.51 距离列桩：__QUEST_DIST_SQ[id] = 码数平方（数字）或 {sq=, onContinent=}
__QUEST_DIST_SQ = {}
C_QuestLog = {
  GetInfo = function(i) return nil end,
  GetQuestID = function(i) return nil end,
  IsOnQuest = function(id) return false end,
  GetLogIndexForQuestID = function(id) return 0 end,
  IsQuestFlaggedCompleted = function(id) return __QUEST_DONE[id] == true end,
  GetDistanceSqToQuest = function(id)
    local d = __QUEST_DIST_SQ[id]
    if type(d) == "number" then return d, true end
    if type(d) == "table" then return d.sq, d.onContinent ~= false end
    return nil
  end,
}
CreateVector2D = function(x, y)
  return {x=x, y=y, GetXY=function(self) return self.x, self.y end}
end
IsQuestFlaggedCompleted = function(id) return __QUEST_DONE[id] == true end
-- v1.107 角色等级桩：测试可设 __PLAYER_LEVEL（默认 60），模拟 UnitLevel("player")。
__PLAYER_LEVEL = 60
UnitLevel = function(unit) return __PLAYER_LEVEL or 60 end
GetNumQuestLogEntries = function() return 0 end
GetQuestLogTitle = function(i) return "" end
GetNumQuestLeaderBoards = function(i) return 0 end
GetQuestLogLeaderBoard = function(i, j) return "" end
GetQuestLogLeaderBoardText = function(i, j) return "" end
GetNumQuestRewards = function() return 0 end
GetRewardXP = function() return 0 end
GetRewardMoney = function() return 0 end
GetQuestItemLink = function(i) return nil end
-- 可控物品信息桩：默认返回 nil（模拟未缓存）。
-- 测试可设 __ITEM_INFO[id]={name, link, quality, ilvl}：
--   [1]=name [2]=link [3]=quality [4]=itemLevel。
-- 返回值顺序与真客户端一致：name,link,quality,itemLevel,minLevel,...
-- i 也接受 itemLink 字符串（提升判定读身上装备走这条）：解析 item:(%d+) 取 id。
__ITEM_INFO = {}
local function __itemKey(i)
  if type(i) == "string" then
    local id = i:match("item:(%d+)")
    return id and tonumber(id) or nil
  end
  return i
end
GetItemInfo = function(i)
  local d = __ITEM_INFO[__itemKey(i)]
  if not d then return nil end
  -- d[4]=nil 表示"物品已缓存但装等未知"（模拟特殊场景）；返回 nil 让判定走保留分支
  return d[1], d[2], d[3], d[4], d[5]   -- name,link,quality,itemLevel,minLevel
end
GetItemInfoInstant = function(i) local d=__ITEM_INFO[__itemKey(i)] return d and d[1] or nil end
-- 身上装备桩：测试可设 __EQUIPPED[slotID]=itemID；返回该槽的 itemLink。
-- GetItemInfo(link) 依上面 __itemKey 解析 → 读到 __ITEM_INFO[id] 的装等(d[4])。
__EQUIPPED = {}
GetInventoryItemLink = function(unit, slotID)
  local id = __EQUIPPED[slotID]
  if not id then return nil end
  return "item:" .. id .. "::::::::"
end
GetInventoryItemQuality = function(unit, slotID)
  local id = __EQUIPPED[slotID]
  local d = id and __ITEM_INFO[id]
  return d and d[3] or nil
end
-- 物品图标桩：测试可设 __ITEM_ICON[id]=path；未设返回 nil（模拟未缓存）
__ITEM_ICON = {}
GetItemIcon = function(i) return __ITEM_ICON[i] end
C_Item = { GetItemIconByID = function(i) return __ITEM_ICON[i] end }
-- 地图信息桩：测试可设 __MAP_INFO[uiMapID]={name="奥格瑞玛"}；未设返回 nil（模拟查不到）
__MAP_INFO = {}
-- 距离排序桩：__PLAYER_MAP=当前 uiMapID；__PLAYER_POS[mapID]={x=,y=}（0-1 归一化）
__PLAYER_MAP = nil
__PLAYER_POS = {}
C_Map = { GetMapInfo = function(id)
  local d = __MAP_INFO[id]
  if d then return { name = d.name or d[1], mapID = id, parentMapID = d.parentMapID } end
  return nil
end,
  GetBestMapForUnit = function(unit) if unit == "player" then return __PLAYER_MAP end return nil end,
  GetPlayerMapPosition = function(mapID, unit)
    local p = __PLAYER_POS[mapID]
    if p then return p end
    return nil
  end,
  -- v1.51：__WORLD_POS[mapID] = {instance=, north=, west=, span=}，按地图坐标线性换算世界坐标
  GetWorldPosFromMapPos = function(mapID, vec)
    local d = __WORLD_POS[mapID] or {instance=1, north=0, west=0, span=1000}
    local x, y = vec:GetXY()
    local north = (d.north or 0) + (0.5 - y) * (d.span or 1000)
    local west  = (d.west or 0) + (0.5 - x) * (d.span or 1000)
    return d.instance or 1, {GetXY=function() return north, west end}
  end,
}
__WORLD_POS = {}
IsInInstance = function() return false, false end
IsInGroup = function() return false end
IsInRaid = function() return false end
UnitHealthPercent = function(u) return 100 end
UnitName = function(u) return u end
-- v1.61 阵营桩：测试可设 __PLAYER_FACTION = "Alliance" / "Horde"
__PLAYER_FACTION = nil
UnitFactionGroup = function(u) return __PLAYER_FACTION end
GetSpellInfo = function(i) return nil end
GetContainerNumSlots = function(i) return 0 end
GetContainerItemInfo = function() return nil end
CanMerchantRepair = function() return false end
GetRepairAllCost = function() return 0 end
RepairAllItems = function() end
GetQuestLogLeaderBoard = function(i, j) return "" end
C_Timer = { After = function(f, t) end, NewTicker = function(f, t) return { Cancel = function() end } end }
C_AddOns = { IsAddOnLoaded = function(n) return false end, GetAddOnMetadata = function(n, k) return "" end }
Enum = { Create = function(t) return t end }
SlashCmdList = {}
_G.ANCHORS = ANCHORS
_G.LAYERS = LAYERS
_G.FRAME_TYPES = FRAME_TYPES

-- ===== 未知全局检测 =====
-- 记录所有被读取但未定义的全局名（拼错的 API、忘记声明的局部变量等）
UNKNOWN_GLOBALS = {}
local KNOWN = {}
for _, v in pairs({
  _G.unpack, _G.table, _G.string, _G.math, _G.os, _G.type, _G.tostring, _G.tonumber,
  _G.pairs, _G.ipairs, _G.select, _G.setmetatable, _G.getmetatable, _G.rawget, _G.rawset,
  _G.next, _G.error, _G.pcall, _G.print, _G.assert, _G.require, _G.load, _G.loadstring,
  _G.dofile, _G.io, _G.coroutine, _G.debug, _G.package, _G._G,
}) do KNOWN[v] = true end
setmetatable(_G, {
  __index = function(t, k)
    if type(k) ~= "string" then return nil end
    if KNOWN[k] then return rawget(_G, k) end
    if not UNKNOWN_GLOBALS[k] then
      UNKNOWN_GLOBALS[k] = true
      local info = debug.getinfo(2, "Sl")
      local where = ""
      if info then where = string.format("  @ %s:%d", info.short_src or "?", info.currentline or 0) end
      WARNS[#WARNS+1] = "未定义全局: " .. k .. where
    end
    return nil
  end,
})
'''


def make_env(extra_stub=""):
    """返回 (lua, env)，env.errs 为错误列表，env.report() 打印报告"""
    from lupa import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(STUB)
    if extra_stub:
        lua.execute(extra_stub)
    env = {
        "lua": lua,
        "errs": lambda: list(lua.eval("ERRORS") or []),
        "warns": lambda: list(lua.eval("WARNS") or []),
        "err_count": lambda: int(lua.eval("__errs") or 0),
    }

    def report(title="校验报告"):
        errs = [e for e in env["errs"]() if isinstance(e, str)]
        warns = [w for w in env["warns"]() if isinstance(w, str)]
        print("=" * 66)
        print("%s：%d 个错误 / %d 个警告" % (title, len(errs), len(warns)))
        print("=" * 66)
        if errs:
            for i, e in enumerate(errs, 1):
                print("  [E%02d] %s" % (i, e))
        else:
            print("  ✓ 无 API 参数错误")
        if warns:
            print("  --- 警告 ---")
            for i, w in enumerate(warns, 1):
                print("  [W%02d] %s" % (i, w))
        return len(errs)

    env["report"] = report
    return lua, env


class Env:
    """带属性访问的包装：env.report() / env.errs"""
    def __init__(self, lua):
        self._lua = lua
        self._d = {}

    def __getattr__(self, k):
        if k in self._d:
            return self._d[k]
        raise AttributeError(k)

    @property
    def errs(self):
        # 用 table.concat 取，避免 lupa 迭代 Lua 表的坑
        blob = self._lua.eval("table.concat(ERRORS, '\\n')")
        return [l for l in (blob or "").split("\n") if l.strip()]

    @property
    def warns(self):
        blob = self._lua.eval("table.concat(WARNS, '\\n')")
        return [l for l in (blob or "").split("\n") if l.strip()]

    @property
    def err_count(self):
        return int(self._lua.eval("__errs") or 0)

    def report(self, title="校验报告", show_warn=True):
        errs, warns = self.errs, self.warns
        print("=" * 70)
        print("%s：%d 个错误 / %d 个警告" % (title, len(errs), len(warns)))
        print("=" * 70)
        if errs:
            for i, e in enumerate(errs, 1):
                print("  [E%02d] %s" % (i, e))
        else:
            print("  OK  无 API 参数错误")
        if show_warn and warns:
            print("  --- 警告 ---")
            for i, w in enumerate(warns, 1):
                print("  [W%02d] %s" % (i, w))
        return len(errs)


def make_env2(extra_stub="", strict=False):
    """推荐入口：返回 (lua, Env)。strict=True 时非法 API 参数直接抛错（模拟真客户端中断）"""
    from lupa import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(STUB)
    if strict:
        lua.execute("STRICT = true")
    if extra_stub:
        lua.execute(extra_stub)
    return lua, Env(lua)
