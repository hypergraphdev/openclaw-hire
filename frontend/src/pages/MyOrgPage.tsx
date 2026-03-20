import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useT } from "../contexts/LanguageContext";
import type { ChatInfo, ChatMessage, MyOrgData, MyOrgPeer, OrgThread, ThreadMessage } from "../types";

const EMOJI_LIST = ["😀","😂","🤣","😊","😍","🥰","😘","😎","🤔","😅","😢","😭","😤","🔥","❤️","👍","👎","👋","🎉","🙏","💯","✨","⭐","🚀","💡","📎","✅","❌","⚡","🌟"];

// Notification sound (short beep via Web Audio API)
function playNotificationSound() {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.value = 800;
    gain.gain.value = 0.1;
    osc.start();
    osc.stop(ctx.currentTime + 0.15);
  } catch { /* ignore */ }
}

function OnlineDot({ online }: { online: boolean }) {
  return <span className={`inline-block h-2 w-2 rounded-full ${online ? "bg-green-400" : "bg-gray-500"}`} />;
}

function Badge({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 bg-red-500 text-white text-[10px] font-bold rounded-full flex items-center justify-center">
      {count > 99 ? "99+" : count}
    </span>
  );
}

function EmojiPicker({ onSelect, onClose }: { onSelect: (e: string) => void; onClose: () => void }) {
  return (
    <div className="absolute bottom-12 left-0 bg-gray-800 border border-gray-700 rounded-lg p-3 shadow-xl z-50 w-[340px]">
      <div className="grid grid-cols-10 gap-1">
        {EMOJI_LIST.map((e) => (
          <button key={e} onClick={() => { onSelect(e); onClose(); }}
            className="w-8 h-8 flex items-center justify-center text-lg hover:bg-gray-700 rounded">{e}</button>
        ))}
      </div>
    </div>
  );
}

function SectionHeader({ title, count, collapsed, onToggle }: { title: string; count: number; collapsed: boolean; onToggle: () => void }) {
  return (
    <button onClick={onToggle} className="w-full flex items-center gap-1 text-xs text-gray-500 mb-2 hover:text-gray-300 transition-colors">
      <span className={`transition-transform ${collapsed ? "-rotate-90" : ""}`}>▾</span>
      {title} ({count})
    </button>
  );
}

type ChatTarget = { type: "dm"; bot: MyOrgPeer } | { type: "thread"; thread: OrgThread };

export function MyOrgPage() {
  const t = useT();
  const [data, setData] = useState<MyOrgData | null>(null);
  const [loading, setLoading] = useState(true);

  // Sections collapse
  const [membersCollapsed, setMembersCollapsed] = useState(false);
  const [threadsCollapsed, setThreadsCollapsed] = useState(false);

  // Threads
  const [threads, setThreads] = useState<OrgThread[]>([]);
  const [showCreateThread, setShowCreateThread] = useState(false);
  const [threadTopic, setThreadTopic] = useState("");
  const [threadParticipants, setThreadParticipants] = useState<string[]>([]);
  const [creatingThread, setCreatingThread] = useState(false);

  // Chat target
  const [target, setTarget] = useState<ChatTarget | null>(null);

  // DM chat state
  const [chatInfo, setChatInfo] = useState<ChatInfo | null>(null);
  const [messages, setMessages] = useState<(ChatMessage | ThreadMessage)[]>([]);
  const [channelId, setChannelId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [wsStatus, setWsStatus] = useState<"connected" | "connecting" | "disconnected">("disconnected");
  const [botTyping, setBotTyping] = useState(false);
  const [showEmoji, setShowEmoji] = useState(false);

  // Image upload
  const [pendingImage, setPendingImage] = useState<{ file: File; preview: string } | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Unread tracking
  const [unreadCounts, setUnreadCounts] = useState<Record<string, number>>({});

  const wsRef = useRef<WebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const myBotIdRef = useRef("");
  const typingTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const userScrolledUp = useRef(false);
  const currentTargetRef = useRef<string>("");

  useEffect(() => {
    api.myOrg().then(setData).finally(() => setLoading(false));
  }, []);

  // Load threads when data is available
  useEffect(() => {
    if (data?.status === "ok") {
      api.myOrgThreads().then((r) => setThreads(r.threads || [])).catch(() => {});
    }
  }, [data?.status]);

  function sortMessages(msgs: (ChatMessage | ThreadMessage)[]) {
    return [...msgs].sort((a, b) => (a.created_at || 0) - (b.created_at || 0));
  }

  // Select DM bot
  const selectDM = useCallback(async (bot: MyOrgPeer) => {
    setTarget({ type: "dm", bot });
    currentTargetRef.current = `dm_${bot.bot_id}`;
    setMessages([]);
    setChannelId(null);
    setChatInfo(null);
    setBotTyping(false);
    setPendingImage(null);
    setShowEmoji(false);
    // Clear unread
    setUnreadCounts((prev) => ({ ...prev, [`dm_${bot.bot_id}`]: 0 }));
    try {
      const info = await api.myOrgChatInfo(bot.name);
      setChatInfo(info);
      myBotIdRef.current = info.admin_bot_id;
      if (info.dm_channel_id) {
        setChannelId(info.dm_channel_id);
        const hist = await api.myOrgChatMessages(info.dm_channel_id, bot.name);
        setMessages(sortMessages(hist.messages));
        setHasMore(hist.has_more);
      }
    } catch { /* */ }
  }, []);

  // Select Thread
  const selectThread = useCallback(async (thread: OrgThread) => {
    setTarget({ type: "thread", thread });
    currentTargetRef.current = `thread_${thread.id}`;
    setMessages([]);
    setChannelId(null);
    setChatInfo(null);
    setBotTyping(false);
    setPendingImage(null);
    setShowEmoji(false);
    setUnreadCounts((prev) => ({ ...prev, [`thread_${thread.id}`]: 0 }));
    try {
      const hist = await api.myOrgThreadMessages(thread.id);
      setMessages(sortMessages(hist.messages));
      setHasMore(hist.has_more);
    } catch { /* */ }
  }, []);

  // WebSocket for DM
  useEffect(() => {
    if (!target || target.type !== "dm" || !chatInfo) return;
    let mounted = true;
    async function connect() {
      setWsStatus("connecting");
      try {
        const { ticket, ws_url } = await api.myOrgChatWsTicket((target as { type: "dm"; bot: MyOrgPeer }).bot.name);
        const ws = new WebSocket(`${ws_url}?ticket=${ticket}`);
        wsRef.current = ws;
        ws.onopen = () => mounted && setWsStatus("connected");
        ws.onclose = () => {
          if (!mounted) return;
          setWsStatus("disconnected");
          wsRef.current = null;
          setTimeout(() => mounted && connect(), 3000);
        };
        ws.onerror = () => ws.close();
        ws.onmessage = (ev) => {
          try {
            const d = JSON.parse(ev.data);
            if (d.type === "typing") {
              setBotTyping(true);
              clearTimeout(typingTimer.current);
              typingTimer.current = setTimeout(() => setBotTyping(false), 5000);
              return;
            }
            if (d.type === "message" && d.message) {
              const msg: ChatMessage = d.message;
              const isFromOther = msg.sender_id !== myBotIdRef.current;
              if (isFromOther) {
                setBotTyping(false);
                clearTimeout(typingTimer.current);
                // Check if this message belongs to the currently viewed chat
                const botTarget = (target as { type: "dm"; bot: MyOrgPeer }).bot;
                const targetKey = `dm_${botTarget.bot_id}`;
                if (currentTargetRef.current !== targetKey) {
                  setUnreadCounts((prev) => ({ ...prev, [targetKey]: (prev[targetKey] || 0) + 1 }));
                }
                playNotificationSound();
              }
              setMessages((prev) => {
                if (prev.some((m) => m.id === msg.id)) return prev;
                return sortMessages([...prev, msg]);
              });
              if (!channelId && msg.channel_id) setChannelId(msg.channel_id);
              if (!userScrolledUp.current) {
                requestAnimationFrame(() => messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }));
              }
            }
          } catch { /* */ }
        };
      } catch { mounted && setWsStatus("disconnected"); }
    }
    connect();
    return () => { mounted = false; wsRef.current?.close(); wsRef.current = null; };
  }, [target?.type === "dm" ? (target as { type: "dm"; bot: MyOrgPeer }).bot.bot_id : null, chatInfo?.admin_bot_id]);

  useEffect(() => {
    if (!userScrolledUp.current) messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  function handleScroll() {
    const el = containerRef.current;
    if (!el) return;
    userScrolledUp.current = el.scrollHeight - el.scrollTop - el.clientHeight > 100;
  }

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setPendingImage({ file, preview: URL.createObjectURL(file) });
    e.target.value = "";
  }

  function cancelImage() {
    if (pendingImage) { URL.revokeObjectURL(pendingImage.preview); setPendingImage(null); }
  }

  async function handleSend() {
    if ((!input.trim() && !pendingImage) || !target || sending) return;
    setSending(true);
    setBotTyping(true);
    clearTimeout(typingTimer.current);
    typingTimer.current = setTimeout(() => setBotTyping(false), 30000);
    try {
      let imageUrl: string | undefined;
      if (pendingImage) {
        setUploading(true);
        const uploaded = await api.myOrgChatUpload(pendingImage.file);
        imageUrl = uploaded.url;
        URL.revokeObjectURL(pendingImage.preview);
        setPendingImage(null);
        setUploading(false);
      }
      if (target.type === "dm") {
        const result = await api.myOrgChatSend(target.bot.name, input.trim(), imageUrl);
        if (result.channel_id && !channelId) setChannelId(result.channel_id);
        setMessages((prev) => {
          if (prev.some((m) => m.id === result.message.id)) return prev;
          return sortMessages([...prev, result.message]);
        });
      } else {
        const result = await api.myOrgThreadSend(target.thread.id, input.trim(), imageUrl);
        setMessages((prev) => {
          if (prev.some((m) => m.id === result.id)) return prev;
          return sortMessages([...prev, result]);
        });
        setBotTyping(false);
      }
      setInput("");
      requestAnimationFrame(() => messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }));
    } catch {
      setBotTyping(false);
      setUploading(false);
      clearTimeout(typingTimer.current);
    }
    setSending(false);
  }

  async function loadMore() {
    if (messages.length === 0 || !target) return;
    const oldest = messages[0];
    try {
      if (target.type === "dm" && channelId) {
        const hist = await api.myOrgChatMessages(channelId, target.bot.name, oldest.id);
        setMessages((prev) => sortMessages([...hist.messages, ...prev]));
        setHasMore(hist.has_more);
      } else if (target.type === "thread") {
        const hist = await api.myOrgThreadMessages(target.thread.id, oldest.id);
        setMessages((prev) => sortMessages([...hist.messages, ...prev]));
        setHasMore(hist.has_more);
      }
    } catch { /* */ }
  }

  async function handleCreateThread() {
    if (!threadTopic.trim()) return;
    setCreatingThread(true);
    try {
      await api.myOrgCreateThread(threadTopic.trim(), threadParticipants);
      setShowCreateThread(false);
      setThreadTopic("");
      setThreadParticipants([]);
      const r = await api.myOrgThreads();
      setThreads(r.threads || []);
    } catch (e: unknown) {
      alert((e as Error).message || "Failed");
    }
    setCreatingThread(false);
  }

  if (loading) return <div className="text-gray-400 text-sm p-6">{t("common.loading")}</div>;

  if (!data || data.status === "no_instances") {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] text-center">
        <div className="text-4xl mb-4">📦</div>
        <h2 className="text-lg text-white font-medium mb-2">{t("myOrg.noInstances")}</h2>
        <p className="text-gray-500 text-sm mb-4">{t("myOrg.noInstancesDesc")}</p>
        <Link to="/catalog" className="text-blue-400 hover:text-blue-300 text-sm">{t("myOrg.goToCatalog")}</Link>
      </div>
    );
  }

  if (data.status === "no_org") {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] text-center">
        <div className="text-4xl mb-4">🔗</div>
        <h2 className="text-lg text-white font-medium mb-2">{t("myOrg.noOrg")}</h2>
        <p className="text-gray-500 text-sm mb-4">{t("myOrg.noOrgDesc")}</p>
        <Link to="/instances" className="text-blue-400 hover:text-blue-300 text-sm">{t("myOrg.goToInstances")}</Link>
      </div>
    );
  }

  const allBots = data.all_bots || [];
  const myBotId = myBotIdRef.current;
  const selectedKey = target ? (target.type === "dm" ? `dm_${target.bot.bot_id}` : `thread_${target.thread.id}`) : "";

  return (
    <div className="h-[calc(100vh-80px)] flex flex-col">
      <div className="px-4 py-3 border-b border-gray-800">
        <h1 className="text-lg font-semibold text-white">{t("myOrg.title")}: {data.org_name}</h1>
        {data.is_default_org && (
          <div className="mt-2 px-3 py-2 bg-yellow-900/30 border border-yellow-700 rounded text-yellow-300 text-xs">⚠ {t("myOrg.defaultOrgWarning")}</div>
        )}
      </div>

      <div className="flex flex-1 min-h-0">
        {/* Sidebar */}
        <div className="w-64 border-r border-gray-800 overflow-auto p-3">
          {/* Members section */}
          <SectionHeader title={t("myOrg.botList")} count={allBots.length} collapsed={membersCollapsed} onToggle={() => setMembersCollapsed(!membersCollapsed)} />
          {!membersCollapsed && (
            <div className="space-y-1 mb-4">
              {allBots.map((bot) => (
                <button key={bot.bot_id} onClick={() => selectDM(bot)}
                  className={`w-full text-left px-3 py-2 rounded-md transition-colors flex items-center gap-2 relative ${
                    selectedKey === `dm_${bot.bot_id}` ? "bg-blue-600/20 border border-blue-600" : "hover:bg-gray-800 border border-transparent"
                  }`}>
                  <OnlineDot online={bot.online} />
                  <span className="text-sm text-gray-200 truncate flex-1">{bot.name}</span>
                  {bot.is_mine && <span className="text-[10px] px-1 py-0.5 rounded bg-blue-600/30 text-blue-400">{t("myOrg.mine")}</span>}
                  <Badge count={unreadCounts[`dm_${bot.bot_id}`] || 0} />
                </button>
              ))}
            </div>
          )}

          {/* Threads section */}
          <SectionHeader title={t("myOrg.threads")} count={threads.length} collapsed={threadsCollapsed} onToggle={() => setThreadsCollapsed(!threadsCollapsed)} />
          {!threadsCollapsed && (
            <div className="space-y-1">
              <button onClick={() => setShowCreateThread(true)}
                className="w-full text-left px-3 py-1.5 text-xs text-blue-400 hover:text-blue-300 hover:bg-gray-800 rounded">
                {t("myOrg.createThread")}
              </button>
              {threads.length === 0 && <div className="text-xs text-gray-600 px-3">{t("myOrg.noThreads")}</div>}
              {threads.map((thread) => (
                <button key={thread.id} onClick={() => selectThread(thread)}
                  className={`w-full text-left px-3 py-2 rounded-md transition-colors flex items-center gap-2 relative ${
                    selectedKey === `thread_${thread.id}` ? "bg-blue-600/20 border border-blue-600" : "hover:bg-gray-800 border border-transparent"
                  }`}>
                  <span className="text-gray-400">#</span>
                  <span className="text-sm text-gray-200 truncate flex-1">{thread.topic}</span>
                  <Badge count={unreadCounts[`thread_${thread.id}`] || 0} />
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Chat area */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Create thread modal */}
          {showCreateThread && (
            <div className="absolute inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={() => setShowCreateThread(false)}>
              <div className="bg-gray-900 border border-gray-700 rounded-lg p-5 w-96 space-y-3" onClick={(e) => e.stopPropagation()}>
                <h3 className="text-sm font-medium text-white">{t("myOrg.createThread")}</h3>
                <input type="text" value={threadTopic} onChange={(e) => setThreadTopic(e.target.value)}
                  placeholder={t("myOrg.threadName")}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-blue-500" />
                <div>
                  <label className="text-xs text-gray-400 block mb-1">{t("myOrg.selectParticipants")}</label>
                  <div className="flex flex-wrap gap-1 max-h-32 overflow-auto">
                    {allBots.filter((b) => !b.is_mine).map((bot) => (
                      <label key={bot.bot_id} className="flex items-center gap-1 px-2 py-1 bg-gray-800 rounded text-xs text-gray-300 cursor-pointer hover:bg-gray-700">
                        <input type="checkbox" checked={threadParticipants.includes(bot.name)}
                          onChange={(e) => {
                            if (e.target.checked) setThreadParticipants((p) => [...p, bot.name]);
                            else setThreadParticipants((p) => p.filter((n) => n !== bot.name));
                          }} className="rounded bg-gray-700 border-gray-600" />
                        {bot.name}
                      </label>
                    ))}
                  </div>
                </div>
                <div className="flex justify-end gap-2">
                  <button onClick={() => setShowCreateThread(false)} className="text-xs text-gray-500 hover:text-gray-300">{t("common.cancel")}</button>
                  <button onClick={handleCreateThread} disabled={creatingThread || !threadTopic.trim()}
                    className="text-xs bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white px-3 py-1.5 rounded">
                    {creatingThread ? t("myOrg.creating") : t("myOrg.createThread")}
                  </button>
                </div>
              </div>
            </div>
          )}

          {!target ? (
            <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">{t("myOrg.selectBot")}</div>
          ) : (
            <>
              {/* Header */}
              <div className="px-4 py-2 border-b border-gray-800 flex items-center gap-2">
                {target.type === "dm" ? (
                  <>
                    <OnlineDot online={target.bot.online} />
                    <span className="text-sm font-medium text-white">{target.bot.name}</span>
                    {target.bot.is_mine && <span className="text-[10px] px-1 py-0.5 rounded bg-blue-600/30 text-blue-400">{t("myOrg.mine")}</span>}
                  </>
                ) : (
                  <>
                    <span className="text-gray-400 text-sm">#</span>
                    <span className="text-sm font-medium text-white">{target.thread.topic}</span>
                  </>
                )}
                <span className={`ml-auto text-[10px] ${wsStatus === "connected" ? "text-green-400" : wsStatus === "connecting" ? "text-yellow-400" : "text-gray-500"}`}>
                  {target.type === "dm" ? (wsStatus === "connected" ? t("chat.connected") : wsStatus === "connecting" ? t("chat.connecting") : t("chat.disconnected")) : ""}
                </span>
              </div>

              {/* Messages */}
              <div ref={containerRef} onScroll={handleScroll} className="flex-1 overflow-auto px-4 py-3 space-y-2">
                {hasMore && <button onClick={loadMore} className="text-xs text-blue-400 hover:text-blue-300 block mx-auto mb-2">{t("chat.loadMore")}</button>}
                {messages.length === 0 && !botTyping && <div className="text-center text-gray-500 text-sm py-8">{t("chat.noMessages")}</div>}
                {messages.map((msg) => {
                  const isSelf = msg.sender_id === myBotId;
                  const hasImage = msg.content?.match(/\[(?:image|图片)\]\((https?:\/\/[^\s)]+)\)/);
                  const textContent = msg.content?.replace(/\[(?:image|图片)\]\(https?:\/\/[^\s)]+\)\n?/, "").trim();
                  return (
                    <div key={msg.id} className={`flex ${isSelf ? "justify-end" : "justify-start"}`}>
                      <div className={`max-w-[75%] rounded-lg px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap break-words ${
                        isSelf ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-200"
                      }`}>
                        {!isSelf && <div className="text-[10px] text-gray-400 mb-0.5">{(msg as ChatMessage).sender_name || msg.sender_id}</div>}
                        {hasImage && <img src={hasImage[1]} alt="" className="max-w-full max-h-48 rounded mb-1" />}
                        {textContent}
                      </div>
                    </div>
                  );
                })}
                {botTyping && (
                  <div className="flex justify-start">
                    <div className="bg-gray-800 text-gray-400 rounded-lg px-3 py-2 text-sm"><span className="animate-pulse">正在输入...</span></div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>

              {/* Image preview */}
              {pendingImage && (
                <div className="px-4 py-2 border-t border-gray-800 flex items-center gap-2">
                  <img src={pendingImage.preview} alt="" className="h-16 rounded" />
                  <button onClick={cancelImage} className="text-xs text-red-400 hover:text-red-300">✕</button>
                </div>
              )}

              {/* Input */}
              <div className="px-4 py-3 border-t border-gray-800">
                <div className="flex items-center gap-2 relative">
                  <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleFileSelect} />
                  <button onClick={() => fileInputRef.current?.click()} disabled={sending}
                    className="shrink-0 p-2 text-gray-400 hover:text-gray-200 disabled:opacity-40" title="上传图片">
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0 0 22.5 18.75V5.25A2.25 2.25 0 0 0 20.25 3H3.75A2.25 2.25 0 0 0 1.5 5.25v13.5A2.25 2.25 0 0 0 3.75 21Zm16.5-13.5a1.125 1.125 0 1 1-2.25 0 1.125 1.125 0 0 1 2.25 0Z" />
                    </svg>
                  </button>
                  <div className="relative">
                    <button onClick={() => setShowEmoji(!showEmoji)} className="shrink-0 p-2 text-gray-400 hover:text-gray-200" title="Emoji">😀</button>
                    {showEmoji && <EmojiPicker onSelect={(e) => setInput((v) => v + e)} onClose={() => setShowEmoji(false)} />}
                  </div>
                  <input type="text" value={input} onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
                    placeholder={pendingImage ? "添加图片说明..." : t("chat.inputPlaceholder")}
                    className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-blue-500"
                    disabled={sending} />
                  <button onClick={handleSend} disabled={(!input.trim() && !pendingImage) || sending}
                    className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm px-4 py-2 rounded-lg">
                    {uploading ? "上传中..." : sending ? t("chat.sending") : t("chat.send")}
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
