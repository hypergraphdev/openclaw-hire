import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useT } from "../contexts/LanguageContext";
import { PixelOffice } from "../components/PixelOffice";
import type { ChatInfo, ChatMessage, MyOrgData, MyOrgPeer, OrgThread, SearchResult, ThreadMessage } from "../types";

const EMOJI_LIST = ["😀","😂","🤣","😊","😍","🥰","😘","😎","🤔","😅","😢","😭","😤","🔥","❤️","👍","👎","👋","🎉","🙏","💯","✨","⭐","🚀","💡","📎","✅","❌","⚡","🌟"];

function friendlyTime(ts: number | string | undefined): string {
  if (!ts) return "";
  const d = typeof ts === "number" ? new Date(ts) : new Date(ts);
  if (isNaN(d.getTime())) return "";
  const now = Date.now();
  const diff = Math.floor((now - d.getTime()) / 1000);
  if (diff < 10) return "刚刚";
  if (diff < 60) return `${diff}秒前`;
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
  const month = d.getMonth() + 1;
  const day = d.getDate();
  const h = String(d.getHours()).padStart(2, "0");
  const m = String(d.getMinutes()).padStart(2, "0");
  return `${month}/${day} ${h}:${m}`;
}

// @ Mention popup — shows all org members, marks in-thread vs not-in-thread
function MentionPopup({ members, filter, onSelect, onClose, threadMembers }: {
  members: { name: string; online: boolean }[];
  filter: string;
  onSelect: (name: string) => void;
  onClose: () => void;
  threadMembers?: Set<string>;
}) {
  const filtered = members.filter((m) => m.name.toLowerCase().includes(filter.toLowerCase()));
  if (filtered.length === 0) return null;
  return (
    <div className="absolute bottom-full left-0 mb-1 bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-50 max-h-48 overflow-auto w-64">
      {filtered.map((m) => {
        const inThread = !threadMembers || threadMembers.has(m.name);
        return (
          <button key={m.name} onClick={() => { onSelect(m.name); onClose(); }}
            className="w-full text-left px-3 py-1.5 text-sm hover:bg-gray-700 flex items-center gap-2">
            <span className={`inline-block h-2 w-2 rounded-full ${m.online ? "bg-green-400" : "bg-gray-500"}`} />
            <span className={inThread ? "text-gray-200" : "text-gray-500"}>{m.name}</span>
            {!inThread && <span className="text-[10px] text-gray-600 ml-auto">群外</span>}
          </button>
        );
      })}
    </div>
  );
}

// Render message content with clickable @mentions and file links
function RenderContent({ content, threadMemberNames, onMentionClick }: {
  content: string;
  threadMemberNames?: Set<string>;
  onMentionClick?: (name: string) => void;
}) {
  // Split by @mentions and markdown links [text](url)
  const parts = content.split(/(@[\w\-\u4e00-\u9fff]+|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\))/g);
  const elements: React.ReactNode[] = [];
  let i = 0;
  while (i < parts.length) {
    const part = parts[i];
    if (!part) { i++; continue; }
    // Check markdown link: [text](url) — captured groups are at i+1 (text) and i+2 (url)
    if (part.match(/^\[.+\]\(https?:\/\//) && i + 2 < parts.length) {
      const text = parts[i + 1] || part;
      const url = parts[i + 2] || "";
      elements.push(
        <a key={i} href={url} target="_blank" rel="noopener noreferrer"
          className="text-blue-300 hover:text-blue-200 underline break-all">
          {text}
        </a>
      );
      i += 3;
      continue;
    }
    // Check @mention
    const mentionMatch = part.match(/^@([\w\-\u4e00-\u9fff]+)$/);
    if (mentionMatch) {
      const name = mentionMatch[1];
      const inThread = !threadMemberNames || threadMemberNames.has(name);
      elements.push(
        <span key={i}
          onClick={() => onMentionClick?.(name)}
          className={`cursor-pointer font-medium ${inThread ? "text-blue-300 hover:text-blue-200" : "text-orange-400 hover:text-orange-300"}`}>
          @{name}
        </span>
      );
      i++;
      continue;
    }
    elements.push(<span key={i}>{part}</span>);
    i++;
  }
  return <>{elements}</>;
}

function playNotificationSound() {
  try { const c = new AudioContext(), o = c.createOscillator(), g = c.createGain(); o.connect(g); g.connect(c.destination); o.frequency.value = 800; g.gain.value = 0.1; o.start(); o.stop(c.currentTime + 0.15); } catch { /* */ }
}

function OnlineDot({ online }: { online: boolean }) {
  return <span className={`inline-block h-2 w-2 rounded-full ${online ? "bg-green-400" : "bg-gray-500"}`} />;
}

function Badge({ count }: { count: number }) {
  if (count <= 0) return null;
  return <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 bg-red-500 text-white text-[10px] font-bold rounded-full flex items-center justify-center">{count > 99 ? "99+" : count}</span>;
}

function EmojiPicker({ onSelect, onClose }: { onSelect: (e: string) => void; onClose: () => void }) {
  return (
    <div className="absolute bottom-12 left-0 bg-gray-800 border border-gray-700 rounded-lg p-3 shadow-xl z-50 w-[340px]">
      <div className="grid grid-cols-10 gap-1">
        {EMOJI_LIST.map((e) => (<button key={e} onClick={() => { onSelect(e); onClose(); }} className="w-8 h-8 flex items-center justify-center text-lg hover:bg-gray-700 rounded">{e}</button>))}
      </div>
    </div>
  );
}

function SectionHeader({ title, count, collapsed, onToggle, action }: { title: string; count: number; collapsed: boolean; onToggle: () => void; action?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1 mb-2">
      <button onClick={onToggle} className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 transition-colors flex-1">
        <span className={`transition-transform ${collapsed ? "-rotate-90" : ""}`}>▾</span>
        {title} ({count})
      </button>
      {action}
    </div>
  );
}

type ChatTarget = { type: "dm"; bot: MyOrgPeer } | { type: "thread"; thread: OrgThread };

export function MyOrgPage() {
  const t = useT();
  const [data, setData] = useState<MyOrgData | null>(null);
  const [loading, setLoading] = useState(true);
  const [membersCollapsed, setMembersCollapsed] = useState(false);
  const [threadsCollapsed, setThreadsCollapsed] = useState(false);
  const [threads, setThreads] = useState<OrgThread[]>([]);

  // Create thread
  const [showCreateThread, setShowCreateThread] = useState(false);
  const [threadTopic, setThreadTopic] = useState("");
  const [threadParticipants, setThreadParticipants] = useState<string[]>([]);
  const [creatingThread, setCreatingThread] = useState(false);
  const [threadBotId, setThreadBotId] = useState("");  // which bot to send as in threads

  // Target + chat state
  const [target, setTarget] = useState<ChatTarget | null>(null);
  const [chatInfo, setChatInfo] = useState<ChatInfo | null>(null);
  const [messages, setMessages] = useState<(ChatMessage | ThreadMessage)[]>([]);
  const [channelId, setChannelId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [wsStatus, setWsStatus] = useState<"connected" | "connecting" | "disconnected">("disconnected");
  const [botTyping, setBotTyping] = useState(false);
  const [showEmoji, setShowEmoji] = useState(false);
  const [pendingImage, setPendingImage] = useState<{ file: File; preview: string } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [unreadCounts, setUnreadCounts] = useState<Record<string, number>>({});

  // Thread management
  const [showThreadMenu, setShowThreadMenu] = useState(false);
  const [showMembers, setShowMembers] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [showRenameTopic, setShowRenameTopic] = useState(false);
  const [showAnnouncement, setShowAnnouncement] = useState(false);

  // Global search
  const [globalSearchQuery, setGlobalSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [highlightMsgId, setHighlightMsgId] = useState("");
  const [searching, setSearching] = useState(false);
  const [showSearchResults, setShowSearchResults] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [searchSuggestions, setSearchSuggestions] = useState<string[]>([]);
  const [showSearchSuggestions, setShowSearchSuggestions] = useState(false);

  // Pixel Office
  const [showOffice, setShowOffice] = useState(false);

  // @ mention
  const [mentionFilter, setMentionFilter] = useState("");
  const [showMention, setShowMention] = useState(false);

  // Invite to thread
  const [showInvite, setShowInvite] = useState(false);
  const [topicDraft, setTopicDraft] = useState("");
  const [announcementDraft, setAnnouncementDraft] = useState("");
  const [threadDetail, setThreadDetail] = useState<{ initiator_id: string; participant_count: number; participants: { bot_id: string; name?: string; online: boolean }[]; context: string | null } | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const generalFileRef = useRef<HTMLInputElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const myBotIdRef = useRef("");        // admin bot id (for DM with own bot)
  const currentThreadIdRef = useRef(""); // track current thread for WS callback
  const myInstanceBotIdRef = useRef(""); // instance bot id (for thread + DM with others)
  const typingTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const userScrolledUp = useRef(false);
  const currentTargetRef = useRef("");

  const [activeOrgId, setActiveOrgId] = useState("");
  useEffect(() => { api.myOrg(activeOrgId || undefined).then(setData).finally(() => setLoading(false)); }, [activeOrgId]);
  useEffect(() => { if (data?.status === "ok") api.myOrgThreads().then((r) => setThreads(r.threads || [])).catch(() => {}); }, [data?.status]);

  const hashRestoredRef = useRef(false);

  function sortMsgs(msgs: (ChatMessage | ThreadMessage)[]) { return [...msgs].sort((a, b) => (a.created_at || 0) - (b.created_at || 0)); }

  // Load thread detail when selecting a thread
  async function loadThreadDetail(threadId: string) {
    try {
      const d = await api.myOrgThreadDetail(threadId);
      setThreadDetail({ initiator_id: d.initiator_id, participant_count: d.participant_count, participants: d.participants, context: d.context });
    } catch { setThreadDetail(null); }
  }

  const selectDM = useCallback(async (bot: MyOrgPeer) => {
    setTarget({ type: "dm", bot }); currentTargetRef.current = `dm_${bot.bot_id}`;
    window.location.hash = `dm/${encodeURIComponent(bot.name)}`;
    setMessages([]); setChannelId(null); setChatInfo(null); setBotTyping(false); setPendingImage(null); setShowEmoji(false);
    setShowThreadMenu(false); setShowMembers(false); setShowSearch(false); setThreadDetail(null);
    setUnreadCounts((p) => ({ ...p, [`dm_${bot.bot_id}`]: 0 }));
    try {
      const info = await api.myOrgChatInfo(bot.name); setChatInfo(info); myBotIdRef.current = info.admin_bot_id;
      if (info.dm_channel_id) { setChannelId(info.dm_channel_id); const h = await api.myOrgChatMessages(info.dm_channel_id, bot.name); setMessages(sortMsgs(h.messages)); setHasMore(h.has_more); }
    } catch { /* */ }
  }, []);

  const selectThread = useCallback(async (thread: OrgThread) => {
    setTarget({ type: "thread", thread }); currentTargetRef.current = `thread_${thread.id}`;
    window.location.hash = `thread/${encodeURIComponent(thread.topic)}`;
    setUnreadCounts((prev) => { const next = { ...prev }; delete next[`thread_${thread.id}`]; return next; });
    setMessages([]); setChannelId(null); setChatInfo(null); setBotTyping(false); setPendingImage(null); setShowEmoji(false);
    setShowThreadMenu(false); setShowMembers(false); setShowSearch(false);
    setUnreadCounts((p) => ({ ...p, [`thread_${thread.id}`]: 0 }));
    await loadThreadDetail(thread.id);
    try { const h = await api.myOrgThreadMessages(thread.id); setMessages(sortMsgs(h.messages)); setHasMore(h.has_more); } catch { /* */ }
  }, []);

  // Restore from URL hash on load (e.g. #dm/HTX_Bill or #thread/Fourth)
  useEffect(() => {
    if (hashRestoredRef.current || !data?.status || data.status !== "ok") return;
    const hash = window.location.hash.replace(/^#/, "");
    if (!hash) return;
    const [kind, name] = hash.split("/").map(decodeURIComponent);
    if (kind === "dm" && name) {
      const bot = (data.all_bots || []).find((b: MyOrgPeer) => b.name === name);
      if (bot) { hashRestoredRef.current = true; selectDM(bot); }
    } else if (kind === "thread" && name && threads.length > 0) {
      const thread = threads.find((t: OrgThread) => t.topic === name);
      if (thread) { hashRestoredRef.current = true; selectThread(thread); }
    }
  }, [data?.status, threads, selectDM, selectThread]);

  // WebSocket for DM
  useEffect(() => {
    if (!target || target.type !== "dm" || !chatInfo) return;
    currentThreadIdRef.current = "";  // clear thread ref when in DM mode
    let mounted = true;
    async function connect() {
      setWsStatus("connecting");
      try {
        const { ticket, ws_url } = await api.myOrgChatWsTicket((target as { type: "dm"; bot: MyOrgPeer }).bot.name);
        const ws = new WebSocket(`${ws_url}?ticket=${ticket}`); wsRef.current = ws;
        ws.onopen = () => mounted && setWsStatus("connected");
        ws.onclose = () => { if (!mounted) return; setWsStatus("disconnected"); wsRef.current = null; setTimeout(() => mounted && connect(), 3000); };
        ws.onerror = () => ws.close();
        ws.onmessage = (ev) => {
          try {
            const d = JSON.parse(ev.data);
            if (d.type === "typing") { setBotTyping(true); clearTimeout(typingTimer.current); typingTimer.current = setTimeout(() => setBotTyping(false), 5000); return; }
            if (d.type === "message" && d.message) {
              const msg: ChatMessage = d.message;
              if (msg.sender_id !== myBotIdRef.current) { setBotTyping(false); clearTimeout(typingTimer.current); playNotificationSound(); }
              setMessages((prev) => prev.some((m) => m.id === msg.id) ? prev : sortMsgs([...prev, msg]));
              if (!userScrolledUp.current) requestAnimationFrame(() => messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }));
            }
          } catch { /* */ }
        };
      } catch { mounted && setWsStatus("disconnected"); }
    }
    connect();
    return () => { mounted = false; wsRef.current?.close(); wsRef.current = null; };
  }, [target?.type === "dm" ? (target as { type: "dm"; bot: MyOrgPeer }).bot.bot_id : null, chatInfo?.admin_bot_id]);

  // WebSocket for Thread — uses instance bot token
  useEffect(() => {
    if (!target || target.type !== "thread") return;
    currentThreadIdRef.current = (target as { type: "thread"; thread: OrgThread }).thread.id;
    let mounted = true;
    async function connect() {
      setWsStatus("connecting");
      try {
        // Use empty target to get instance bot ws ticket
        // Use instance bot token for thread WS (bot is thread participant)
        const params = new URLSearchParams({ mode: "thread" });
        const { ticket, ws_url } = await api.myOrgChatWsTicket("", params);
        const ws = new WebSocket(`${ws_url}?ticket=${ticket}`);
        wsRef.current = ws;
        ws.onopen = () => {
          if (!mounted) return;
          setWsStatus("connected");
          // Bot WS auto-receives thread_message for threads it participates in (no subscribe needed)
        };
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
            if (d.type === "thread_message" && d.message) {
              const msg = d.message;
              const msgThreadId = d.thread_id || msg.thread_id || "";
              const currentThreadId = currentThreadIdRef.current;
              const myNames = new Set((data?.my_bots || []).map((b: { agent_name: string }) => b.agent_name));
              if (chatInfo?.admin_bot_name) myNames.add(chatInfo.admin_bot_name);
              const senderName = msg.sender_name || "";
              const isFromOther = !myNames.has(senderName);

              if (msgThreadId === currentThreadId) {
                // Message belongs to current thread — show in chat
                setMessages((prev) => {
                  if (prev.some((m) => m.id === msg.id)) return prev;
                  return sortMsgs([...prev, msg]);
                });
                if (isFromOther) playNotificationSound();
                if (!userScrolledUp.current) {
                  requestAnimationFrame(() => messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }));
                }
              } else if (isFromOther && msgThreadId) {
                // Message for another thread — update unread count
                setUnreadCounts((prev) => ({ ...prev, [`thread_${msgThreadId}`]: (prev[`thread_${msgThreadId}`] || 0) + 1 }));
                playNotificationSound();
              }
            }
          } catch { /* */ }
        };
        // Thread WS doesn't need identity tracking - isSelf uses myNames
      } catch { mounted && setWsStatus("disconnected"); }
    }
    connect();
    return () => { mounted = false; wsRef.current?.close(); wsRef.current = null; };
  }, [target?.type === "thread" ? (target as { type: "thread"; thread: OrgThread }).thread.id : null]);

  useEffect(() => { if (!userScrolledUp.current) messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages.length]);

  function handleScroll() { const el = containerRef.current; if (el) userScrolledUp.current = el.scrollHeight - el.scrollTop - el.clientHeight > 100; }
  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) { const f = e.target.files?.[0]; if (f) setPendingImage({ file: f, preview: URL.createObjectURL(f) }); e.target.value = ""; }
  function cancelImage() { if (pendingImage) { URL.revokeObjectURL(pendingImage.preview); setPendingImage(null); } }

  async function handleSend() {
    if ((!input.trim() && !pendingImage) || !target || sending) return;
    setSending(true); setBotTyping(true); clearTimeout(typingTimer.current); typingTimer.current = setTimeout(() => setBotTyping(false), 30000);
    try {
      let imgUrl: string | undefined;
      if (pendingImage) { setUploading(true); const u = await api.myOrgChatUpload(pendingImage.file); imgUrl = u.url; URL.revokeObjectURL(pendingImage.preview); setPendingImage(null); setUploading(false); }
      if (target.type === "dm") {
        const r = await api.myOrgChatSend(target.bot.name, input.trim(), imgUrl);
        if (r.channel_id && !channelId) setChannelId(r.channel_id);
        setMessages((p) => p.some((m) => m.id === r.message.id) ? p : sortMsgs([...p, r.message]));
      } else {
        const r = await api.myOrgThreadSend(target.thread.id, input.trim(), imgUrl, threadBotId || undefined);
        setMessages((p) => p.some((m) => m.id === r.id) ? p : sortMsgs([...p, r]));
        setBotTyping(false);
      }
      setInput(""); requestAnimationFrame(() => messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }));
    } catch { setBotTyping(false); setUploading(false); clearTimeout(typingTimer.current); }
    setSending(false);
  }

  async function loadMore() {
    if (messages.length === 0 || !target) return;
    const oldest = messages[0];
    try {
      if (target.type === "dm" && channelId) { const h = await api.myOrgChatMessages(channelId, target.bot.name, oldest.id); setMessages((p) => sortMsgs([...h.messages, ...p])); setHasMore(h.has_more); }
      else if (target.type === "thread") { const h = await api.myOrgThreadMessages(target.thread.id, String(oldest.created_at || oldest.id)); setMessages((p) => sortMsgs([...h.messages, ...p])); setHasMore(h.has_more); }
    } catch { /* */ }
  }

  async function handleCreateThread() {
    if (!threadTopic.trim()) return; setCreatingThread(true);
    try { await api.myOrgCreateThread(threadTopic.trim(), threadParticipants); setShowCreateThread(false); setThreadTopic(""); setThreadParticipants([]); const r = await api.myOrgThreads(); setThreads(r.threads || []); }
    catch (e: unknown) { alert((e as Error).message || "Failed"); }
    setCreatingThread(false);
  }

  async function handleRenameTopic() {
    if (!topicDraft.trim() || !target || target.type !== "thread") return;
    try { await api.myOrgThreadUpdate(target.thread.id, { topic: topicDraft.trim() }); setShowRenameTopic(false); const r = await api.myOrgThreads(); setThreads(r.threads || []); setTarget({ type: "thread", thread: { ...target.thread, topic: topicDraft.trim() } }); }
    catch (e: unknown) { alert((e as Error).message || "Failed"); }
  }

  async function handleSaveAnnouncement() {
    if (!target || target.type !== "thread") return;
    try { await api.myOrgThreadUpdate(target.thread.id, { context: { announcement: announcementDraft } }); setShowAnnouncement(false); await loadThreadDetail(target.thread.id); }
    catch (e: unknown) { alert((e as Error).message || "Failed"); }
  }

  async function handleLeaveThread() {
    if (!target || target.type !== "thread") return;
    if (!confirm("确定退出群聊？")) return;
    try { await api.myOrgThreadLeave(target.thread.id); setTarget(null); const r = await api.myOrgThreads(); setThreads(r.threads || []); }
    catch (e: unknown) { alert((e as Error).message || "Failed"); }
  }

  function selectAllParticipants() {
    const all = (data?.all_bots || []).map((b) => b.name);
    setThreadParticipants(all);
  }

  // @ mention handling in chat input
  function handleInputChange(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) {
    const val = e.target.value;
    setInput(val);
    // Check for @ trigger
    const atMatch = val.match(/@([\w\-\u4e00-\u9fff]*)$/);
    if (atMatch) {
      setMentionFilter(atMatch[1]);
      setShowMention(true);
    } else {
      setShowMention(false);
    }
  }

  function handleMentionSelect(name: string) {
    // Replace @partial with @name
    setInput((prev) => prev.replace(/@[\w\-\u4e00-\u9fff]*$/, `@${name} `));
    setShowMention(false);
  }

  // Global search
  async function handleGlobalSearch() {
    if (!globalSearchQuery.trim()) return;
    // First sync
    setSyncing(true);
    try { await api.myOrgSearchSync(); } catch { /* */ }
    setSyncing(false);

    // Parse search syntax
    const params: { q?: string; in?: string; from?: string; to?: string } = {};
    let q = globalSearchQuery;

    const inMatch = q.match(/in:@?([\w\-\u4e00-\u9fff#]+)/);
    if (inMatch) { params.in = inMatch[1]; q = q.replace(inMatch[0], "").trim(); }

    const fromMatch = q.match(/from:@?([\w\-\u4e00-\u9fff]+)/);
    if (fromMatch) { params.from = fromMatch[1]; q = q.replace(fromMatch[0], "").trim(); }

    const toMatch = q.match(/to:@?([\w\-\u4e00-\u9fff]+)/);
    if (toMatch) { params.to = toMatch[1]; q = q.replace(toMatch[0], "").trim(); }

    if (q) params.q = q;

    setSearching(true);
    try {
      const r = await api.myOrgSearch(params);
      setSearchResults(r.results || []);
      setShowSearchResults(true);
    } catch { /* */ }
    setSearching(false);
  }

  function handleSearchInputChange(val: string) {
    setGlobalSearchQuery(val);
    // Show suggestions when typing @
    const atMatch = val.match(/@([\w\-\u4e00-\u9fff]*)$/);
    if (atMatch) {
      const filter = atMatch[1].toLowerCase();
      const names = [...allBots.map((b) => b.name), ...threads.map((t) => `#${t.topic}`)];
      setSearchSuggestions(names.filter((n) => n.toLowerCase().includes(filter)));
      setShowSearchSuggestions(true);
    } else {
      setShowSearchSuggestions(false);
    }
  }

  function handleSearchSuggestionSelect(name: string) {
    setGlobalSearchQuery((prev) => prev.replace(/@[\w\-\u4e00-\u9fff#]*$/, `@${name} `));
    setShowSearchSuggestions(false);
  }

  const allBots = data?.all_bots || [];
  const myBotNames = useMemo(() => new Set((data?.my_bots || []).map((b) => b.agent_name)), [data?.my_bots]);

  if (loading) return <div className="text-gray-400 text-sm p-6">{t("common.loading")}</div>;
  if (!data || data.status === "no_instances") return (<div className="flex flex-col items-center justify-center h-[60vh] text-center"><div className="text-4xl mb-4">📦</div><h2 className="text-lg text-white font-medium mb-2">{t("myOrg.noInstances")}</h2><p className="text-gray-500 text-sm mb-4">{t("myOrg.noInstancesDesc")}</p><Link to="/catalog" className="text-blue-400 hover:text-blue-300 text-sm">{t("myOrg.goToCatalog")}</Link></div>);
  if (data.status === "no_org") return (<div className="flex flex-col items-center justify-center h-[60vh] text-center"><div className="text-4xl mb-4">🔗</div><h2 className="text-lg text-white font-medium mb-2">{t("myOrg.noOrg")}</h2><p className="text-gray-500 text-sm mb-4">{t("myOrg.noOrgDesc")}</p><Link to="/instances" className="text-blue-400 hover:text-blue-300 text-sm">{t("myOrg.goToInstances")}</Link></div>);

  const myBotId = myBotIdRef.current;
  const selectedKey = target ? (target.type === "dm" ? `dm_${target.bot.bot_id}` : `thread_${target.thread.id}`) : "";
  const isThreadCreator = target?.type === "thread" && threadDetail?.initiator_id && data.my_bots?.some((b) => {
    // Check if any of my bots is the initiator
    return threadDetail.participants?.some((p) => p.bot_id === threadDetail.initiator_id && p.name === b.agent_name);
  });
  const announcement = threadDetail?.context ? (() => { try { return JSON.parse(threadDetail.context).announcement || ""; } catch { return ""; } })() : "";
  const filteredMessages = showSearch && searchQuery ? messages.filter((m) => m.content?.toLowerCase().includes(searchQuery.toLowerCase())) : messages;
  const threadMemberNames = threadDetail ? new Set(threadDetail.participants.map((p) => p.name || "").filter(Boolean)) : undefined;
  function handleMentionClick(name: string) {
    const bot = allBots.find((b) => b.name === name);
    if (bot) selectDM(bot);
  }

  return (
    <div className="h-[calc(100vh-80px)] flex flex-col">
      <div className="px-4 py-3 border-b border-gray-800">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 shrink-0">
            <h1 className="text-lg font-semibold text-white">{t("myOrg.title")}:</h1>
            {data.orgs && data.orgs.length > 1 ? (
              <select value={data.org_id || ""} onChange={(e) => { setActiveOrgId(e.target.value); setTarget(null); setLoading(true); }}
                className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white focus:outline-none focus:border-blue-500">
                {data.orgs.map((o) => (
                  <option key={o.org_id} value={o.org_id}>{o.org_name}{o.is_default ? " (默认)" : ""}</option>
                ))}
              </select>
            ) : (
              <span className="text-lg font-semibold text-white">{data.org_name}</span>
            )}
          </div>
          <div className="flex-1" />
          <button
            onClick={() => setShowOffice((v) => !v)}
            className={`shrink-0 text-xs px-2.5 py-1.5 rounded-md border transition-colors ${showOffice ? "bg-blue-600/20 border-blue-600 text-blue-400" : "bg-gray-800 border-gray-700 text-gray-400 hover:text-gray-200 hover:border-gray-600"}`}
          >
            {showOffice ? "🏢 关闭办公室" : "🏢 办公室视图"}
          </button>
          <div className="relative w-80">
            <input type="text" value={globalSearchQuery}
              onChange={(e) => handleSearchInputChange(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleGlobalSearch(); }}
              placeholder="搜索消息... (支持 in:@name from:@name to:@name)"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-blue-500 placeholder-gray-600" />
            {(searching || syncing) && <span className="absolute right-2 top-1.5 text-[10px] text-yellow-400">{syncing ? "同步中..." : "搜索中..."}</span>}
            {showSearchSuggestions && searchSuggestions.length > 0 && (
              <div className="absolute top-full left-0 mt-1 bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-50 max-h-32 overflow-auto w-full">
                {searchSuggestions.slice(0, 8).map((s) => (
                  <button key={s} onClick={() => handleSearchSuggestionSelect(s)}
                    className="w-full text-left px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700">{s}</button>
                ))}
              </div>
            )}
          </div>
        </div>
        {/* Search results overlay */}
        {showSearchResults && (
          <div className="mt-2 bg-gray-800 border border-gray-700 rounded-lg p-3 max-h-60 overflow-auto">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-gray-400">搜索结果 ({searchResults.length})</span>
              <button onClick={() => setShowSearchResults(false)} className="text-xs text-gray-500 hover:text-gray-300">✕ 关闭</button>
            </div>
            {searchResults.length === 0 ? (
              <div className="text-xs text-gray-500 text-center py-2">无结果</div>
            ) : searchResults.map((r) => (
              <div key={r.id} className="px-2 py-1.5 hover:bg-gray-700 rounded text-xs cursor-pointer" onClick={async () => {
                // Jump to conversation and scroll to message
                setHighlightMsgId(r.id);
                if (r.channel_type === "dm") {
                  const bot = allBots.find((b) => b.name === r.channel_name);
                  if (bot) selectDM(bot);
                } else if (r.channel_type === "thread") {
                  const thread = threads.find((t) => t.topic === r.channel_name);
                  if (thread) {
                    selectThread(thread);
                    // Load messages around the target — keep loading older until we find it
                    try {
                      const firstPage = await api.myOrgThreadMessages(thread.id);
                      let allMsgs = firstPage.messages || [];
                      let found = allMsgs.some((m) => m.id === r.id);
                      let attempts = 0;
                      while (!found && allMsgs.length > 0 && attempts < 10) {
                        const oldest = allMsgs[allMsgs.length - 1];
                        const more = await api.myOrgThreadMessages(thread.id, String(oldest.created_at || oldest.id));
                        if (!more.messages?.length) break;
                        allMsgs = [...allMsgs, ...more.messages];
                        found = more.messages.some((m: { id: string }) => m.id === r.id);
                        attempts++;
                      }
                      if (found) {
                        setMessages(sortMsgs(allMsgs));
                        setHasMore(true);
                      }
                    } catch { /* best effort */ }
                  }
                }
                setShowSearchResults(false);
                // Scroll to target after render
                setTimeout(() => {
                  const el = document.getElementById(`msg-${r.id}`);
                  if (el) {
                    el.scrollIntoView({ behavior: "smooth", block: "center" });
                    el.classList.add("ring-2", "ring-yellow-400");
                    setTimeout(() => { el.classList.remove("ring-2", "ring-yellow-400"); setHighlightMsgId(""); }, 3000);
                  }
                }, 500);
              }}>
                <div className="flex items-center gap-2 text-gray-500">
                  <span>{r.channel_type === "thread" ? "#" : "@"}{r.channel_name}</span>
                  <span>·</span>
                  <span>{r.sender_name}</span>
                  <span>·</span>
                  <span>{new Date(r.created_at).toLocaleString()}</span>
                </div>
                <div className="text-gray-300 mt-0.5 truncate">{r.content}</div>
              </div>
            ))}
          </div>
        )}
        {data.is_default_org && <div className="mt-2 px-3 py-2 bg-yellow-900/30 border border-yellow-700 rounded text-yellow-300 text-xs">⚠ {t("myOrg.defaultOrgWarning")}</div>}
      </div>

      {showOffice && (
        <div className="px-4 py-2 border-b border-gray-800 max-h-[40vh] overflow-auto">
          <PixelOffice
            bots={allBots.map((b) => ({ name: b.name, online: b.online, bot_id: b.bot_id }))}
            myBotNames={myBotNames}
            onBotClick={(name) => {
              const bot = allBots.find((b) => b.name === name);
              if (bot) selectDM(bot);
            }}
          />
        </div>
      )}

      <div className="flex flex-1 min-h-0">
        {/* Sidebar */}
        <div className="w-64 border-r border-gray-800 overflow-auto p-3">
          <SectionHeader title={t("myOrg.botList")} count={allBots.length} collapsed={membersCollapsed} onToggle={() => setMembersCollapsed(!membersCollapsed)} />
          {!membersCollapsed && <div className="space-y-1 mb-4">{allBots.map((bot) => (
            <button key={bot.bot_id} onClick={() => selectDM(bot)} className={`w-full text-left px-3 py-2 rounded-md transition-colors flex items-center gap-2 relative ${selectedKey === `dm_${bot.bot_id}` ? "bg-blue-600/20 border border-blue-600" : "hover:bg-gray-800 border border-transparent"}`}>
              <OnlineDot online={bot.online} /><span className="text-sm text-gray-200 truncate flex-1">{bot.name}</span>
              {bot.is_mine && <span className="text-[10px] px-1 py-0.5 rounded bg-blue-600/30 text-blue-400">{t("myOrg.mine")}</span>}
              <Badge count={unreadCounts[`dm_${bot.bot_id}`] || 0} />
            </button>
          ))}</div>}

          <SectionHeader title={t("myOrg.threads")} count={threads.length} collapsed={threadsCollapsed} onToggle={() => setThreadsCollapsed(!threadsCollapsed)}
            action={<button onClick={() => setShowCreateThread(true)} className="text-gray-500 hover:text-blue-400 text-sm" title={t("myOrg.createThread")}>+</button>} />
          {!threadsCollapsed && <div className="space-y-1">
            {threads.length === 0 && <div className="text-xs text-gray-600 px-3">{t("myOrg.noThreads")}</div>}
            {threads.map((thread) => (
              <button key={thread.id} onClick={() => selectThread(thread)} className={`w-full text-left px-3 py-2 rounded-md transition-colors flex items-center gap-2 relative ${selectedKey === `thread_${thread.id}` ? "bg-blue-600/20 border border-blue-600" : "hover:bg-gray-800 border border-transparent"}`}>
                <span className="text-gray-400">#</span><span className="text-sm text-gray-200 truncate flex-1">{thread.topic}</span>
                {thread.participant_count != null && <span className="text-[10px] text-gray-500">({thread.participant_count})</span>}
                <Badge count={unreadCounts[`thread_${thread.id}`] || 0} />
              </button>
            ))}
          </div>}
        </div>

        {/* Chat */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Create thread modal */}
          {showCreateThread && (
            <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={() => setShowCreateThread(false)}>
              <div className="bg-gray-900 border border-gray-700 rounded-lg p-5 w-96 space-y-3" onClick={(e) => e.stopPropagation()}>
                <h3 className="text-sm font-medium text-white">{t("myOrg.createThread")}</h3>
                <input type="text" value={threadTopic} onChange={(e) => setThreadTopic(e.target.value)} placeholder={t("myOrg.threadName")}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-blue-500" />
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-xs text-gray-400">{t("myOrg.selectParticipants")}</label>
                    <button onClick={selectAllParticipants} className="text-[10px] text-blue-400 hover:text-blue-300">全选</button>
                  </div>
                  <div className="flex flex-wrap gap-1 max-h-32 overflow-auto">
                    {allBots.map((bot) => (
                      <label key={bot.bot_id} className="flex items-center gap-1 px-2 py-1 bg-gray-800 rounded text-xs text-gray-300 cursor-pointer hover:bg-gray-700">
                        <input type="checkbox" checked={threadParticipants.includes(bot.name)} onChange={(e) => { if (e.target.checked) setThreadParticipants((p) => [...p, bot.name]); else setThreadParticipants((p) => p.filter((n) => n !== bot.name)); }} className="rounded bg-gray-700 border-gray-600" />
                        {bot.name}{bot.is_mine && <span className="text-[9px] px-1 py-0.5 rounded bg-blue-600/30 text-blue-400">{t("myOrg.mine")}</span>}
                      </label>
                    ))}
                  </div>
                </div>
                <div className="flex justify-end gap-2">
                  <button onClick={() => setShowCreateThread(false)} className="text-xs text-gray-500 hover:text-gray-300">{t("common.cancel")}</button>
                  <button onClick={handleCreateThread} disabled={creatingThread || !threadTopic.trim()} className="text-xs bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white px-3 py-1.5 rounded">
                    {creatingThread ? t("myOrg.creating") : t("common.ok")}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Members modal */}
          {showMembers && threadDetail && (
            <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={() => setShowMembers(false)}>
              <div className="bg-gray-900 border border-gray-700 rounded-lg p-5 w-80 space-y-2" onClick={(e) => e.stopPropagation()}>
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-medium text-white">群成员 ({threadDetail.participant_count})</h3>
                  <button onClick={() => { setShowMembers(false); setShowInvite(true); }}
                    className="text-xs text-blue-400 hover:text-blue-300" title="邀请成员">+ 邀请</button>
                </div>
                <div className="max-h-60 overflow-auto space-y-1">
                  {threadDetail.participants.map((p) => {
                    const isMine = (data?.my_bots || []).some((b: { agent_name: string }) => b.agent_name === p.name);
                    const isCreator = p.bot_id === threadDetail.initiator_id;
                    const myBotIsCreator = (data?.my_bots || []).some((b: { agent_name: string }) => {
                      const found = threadDetail.participants.find((pp) => pp.name === b.agent_name);
                      return found?.bot_id === threadDetail.initiator_id;
                    });
                    return (
                    <div key={p.bot_id} className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-gray-800 group">
                      <button onClick={() => {
                        const bot = allBots.find((b) => b.name === p.name);
                        if (bot) { selectDM(bot); setShowMembers(false); }
                      }} className="flex items-center gap-2 flex-1 text-left">
                        <OnlineDot online={p.online} /><span className="text-sm text-gray-200">{p.name || p.bot_id.substring(0, 8)}</span>
                        {isCreator && <span className="text-[10px] px-1 py-0.5 rounded bg-amber-700/50 text-amber-200">创建者</span>}
                        {isMine && <span className="text-[10px] px-1 py-0.5 rounded bg-blue-600/30 text-blue-400">{t("myOrg.mine")}</span>}
                      </button>
                      <span className="text-[10px] text-gray-600 cursor-pointer" onClick={() => {
                        const bot = allBots.find((b) => b.name === p.name);
                        if (bot) { selectDM(bot); setShowMembers(false); }
                      }}>私聊 →</span>
                      {!isCreator && myBotIsCreator && (
                        <button onClick={async (e) => {
                          e.stopPropagation();
                          if (!confirm(`确定将 ${p.name} 移出群聊？`)) return;
                          try {
                            await api.myOrgThreadKick(target!.type === "thread" ? (target as { type: "thread"; thread: OrgThread }).thread.id : "", p.bot_id);
                            await loadThreadDetail((target as { type: "thread"; thread: OrgThread }).thread.id);
                          } catch (err: unknown) { alert((err as Error).message || "Failed"); }
                        }} className="text-[10px] text-red-500 opacity-0 group-hover:opacity-100 hover:text-red-300">移除</button>
                      )}
                    </div>
                    );
                  })}
                </div>
                <button onClick={() => setShowMembers(false)} className="text-xs text-gray-500 hover:text-gray-300 w-full text-center pt-2">{t("common.close")}</button>
              </div>
            </div>
          )}

          {/* Invite to thread modal */}
          {showInvite && target?.type === "thread" && (
            <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={() => setShowInvite(false)}>
              <div className="bg-gray-900 border border-gray-700 rounded-lg p-5 w-80 space-y-3" onClick={(e) => e.stopPropagation()}>
                <h3 className="text-sm font-medium text-white">邀请成员加入群聊</h3>
                <div className="max-h-48 overflow-auto space-y-1">
                  {allBots.filter((b) => !threadMemberNames?.has(b.name)).map((bot) => (
                    <button key={bot.bot_id} onClick={async () => {
                      try {
                        await api.myOrgThreadInvite(target.thread.id, bot.name);
                        await loadThreadDetail(target.thread.id);
                      } catch (e: unknown) { alert((e as Error).message || "Failed"); }
                    }} className="w-full text-left flex items-center gap-2 px-2 py-1.5 rounded hover:bg-gray-800">
                      <OnlineDot online={bot.online} />
                      <span className="text-sm text-gray-200">{bot.name}</span>
                      <span className="ml-auto text-[10px] text-blue-400">邀请</span>
                    </button>
                  ))}
                  {allBots.filter((b) => !threadMemberNames?.has(b.name)).length === 0 && (
                    <div className="text-xs text-gray-500 text-center py-2">所有成员都已在群中</div>
                  )}
                </div>
                <button onClick={() => setShowInvite(false)} className="text-xs text-gray-500 hover:text-gray-300 w-full text-center">{t("common.close")}</button>
              </div>
            </div>
          )}

          {/* Rename topic modal */}
          {showRenameTopic && (
            <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={() => setShowRenameTopic(false)}>
              <div className="bg-gray-900 border border-gray-700 rounded-lg p-5 w-80 space-y-3" onClick={(e) => e.stopPropagation()}>
                <h3 className="text-sm font-medium text-white">修改群名</h3>
                <input type="text" value={topicDraft} onChange={(e) => setTopicDraft(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-blue-500"
                  onKeyDown={(e) => e.key === "Enter" && handleRenameTopic()} />
                <div className="flex justify-end gap-2">
                  <button onClick={() => setShowRenameTopic(false)} className="text-xs text-gray-500">{t("common.cancel")}</button>
                  <button onClick={handleRenameTopic} className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded">{t("common.ok")}</button>
                </div>
              </div>
            </div>
          )}

          {/* Announcement modal */}
          {showAnnouncement && (
            <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={() => setShowAnnouncement(false)}>
              <div className="bg-gray-900 border border-gray-700 rounded-lg p-5 w-96 space-y-3" onClick={(e) => e.stopPropagation()}>
                <h3 className="text-sm font-medium text-white">群公告</h3>
                <textarea value={announcementDraft} onChange={(e) => setAnnouncementDraft(e.target.value)} rows={4}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-blue-500 resize-none" placeholder="输入群公告内容..." />
                <div className="flex justify-end gap-2">
                  <button onClick={() => setShowAnnouncement(false)} className="text-xs text-gray-500">{t("common.cancel")}</button>
                  <button onClick={handleSaveAnnouncement} className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded">{t("common.save")}</button>
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
                  <><OnlineDot online={target.bot.online} /><span className="text-sm font-medium text-white">{target.bot.name}</span>
                    {target.bot.is_mine && <span className="text-[10px] px-1 py-0.5 rounded bg-blue-600/30 text-blue-400">{t("myOrg.mine")}</span>}</>
                ) : (
                  <><span className="text-gray-400 text-sm">#</span><span className="text-sm font-medium text-white">{target.thread.topic}</span>
                    {threadDetail && <span className="text-xs text-gray-500">({threadDetail.participant_count})</span>}</>
                )}

                {/* DM status */}
                {target.type === "dm" && <span className={`ml-auto text-[10px] ${wsStatus === "connected" ? "text-green-400" : wsStatus === "connecting" ? "text-yellow-400" : "text-gray-500"}`}>
                  {wsStatus === "connected" ? t("chat.connected") : wsStatus === "connecting" ? t("chat.connecting") : t("chat.disconnected")}
                </span>}

                {/* Thread menu */}
                {target.type === "thread" && (
                  <div className="ml-auto relative">
                    <button onClick={() => setShowThreadMenu(!showThreadMenu)} className="text-gray-400 hover:text-gray-200 p-1">⋯</button>
                    {showThreadMenu && (
                      <div className="absolute right-0 top-8 bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-50 py-1 w-36">
                        <button onClick={() => { setShowMembers(true); setShowThreadMenu(false); }} className="w-full text-left px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700">👥 成员列表</button>
                        <button onClick={() => { setShowSearch(!showSearch); setShowThreadMenu(false); }} className="w-full text-left px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700">🔍 消息搜索</button>
                        {isThreadCreator && <>
                          <button onClick={() => { setTopicDraft(target.thread.topic); setShowRenameTopic(true); setShowThreadMenu(false); }} className="w-full text-left px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700">✏️ 修改群名</button>
                          <button onClick={() => { setAnnouncementDraft(announcement); setShowAnnouncement(true); setShowThreadMenu(false); }} className="w-full text-left px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700">📢 群公告</button>
                        </>}
                        {!isThreadCreator && <button onClick={() => { handleLeaveThread(); setShowThreadMenu(false); }} className="w-full text-left px-3 py-1.5 text-xs text-red-400 hover:bg-gray-700">🚪 退出群聊</button>}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Announcement banner */}
              {target.type === "thread" && announcement && (
                <div className="px-4 py-2 bg-blue-900/20 border-b border-blue-800/30 text-xs text-blue-300">📢 {announcement}</div>
              )}

              {/* Search bar */}
              {showSearch && (
                <div className="px-4 py-2 border-b border-gray-800">
                  <input type="text" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="搜索消息内容..."
                    className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-xs text-gray-100 focus:outline-none focus:border-blue-500" />
                </div>
              )}

              {/* Messages */}
              <div ref={containerRef} onScroll={handleScroll} className="flex-1 overflow-auto px-4 py-3 space-y-2">
                {hasMore && <button onClick={loadMore} className="text-xs text-blue-400 hover:text-blue-300 block mx-auto mb-2">{t("chat.loadMore")}</button>}
                {filteredMessages.length === 0 && !botTyping && <div className="text-center text-gray-500 text-sm py-8">{showSearch ? "无搜索结果" : t("chat.noMessages")}</div>}
                {filteredMessages.map((msg) => {
                  const senderName = (msg as ChatMessage).sender_name || "";
                  const myNames = new Set((data?.my_bots || []).map((b: { agent_name: string }) => b.agent_name));
                  if (chatInfo?.admin_bot_name) myNames.add(chatInfo.admin_bot_name);

                  // DM with own bot: only admin bot messages are "self" (right side)
                  // DM with others' bot: own instance bot messages are "self"
                  // Thread: all own bot messages are "self"
                  let isSelf: boolean;
                  if (target?.type === "dm") {
                    const targetIsMyBot = myNames.has(target.bot.name);
                    if (targetIsMyBot) {
                      // DM own bot: right = admin bot only, left = own instance bot
                      isSelf = msg.sender_id === myBotId || senderName === chatInfo?.admin_bot_name;
                    } else {
                      // DM others' bot: right = my instance bot, left = their bot
                      isSelf = msg.sender_id === myInstanceBotIdRef.current || myNames.has(senderName);
                    }
                  } else {
                    // Thread: right = all my bots + admin bot
                    isSelf = msg.sender_id === myBotId || msg.sender_id === myInstanceBotIdRef.current || myNames.has(senderName);
                  }
                  const hasImage = msg.content?.match(/\[(?:image|图片)\]\((https?:\/\/[^\s)]+)\)/);
                  const textContent = msg.content?.replace(/\[(?:image|图片)\]\(https?:\/\/[^\s)]+\)\n?/, "").trim();
                  const msgTime = friendlyTime(msg.created_at);
                  return (
                    <div key={msg.id} id={`msg-${msg.id}`} className={`flex ${isSelf ? "justify-end" : "justify-start"} transition-all duration-300 ${highlightMsgId === msg.id ? "ring-2 ring-yellow-400 rounded-lg" : ""}`}>
                      <div className={`max-w-[75%] rounded-lg px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap break-words ${isSelf ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-200"}`}>
                        <div className={`flex items-center gap-2 mb-0.5 ${isSelf ? "justify-end" : "justify-start"}`}>
                          {!isSelf && <span className="text-[10px] text-gray-400">{senderName}</span>}
                          {isSelf && (target?.type === "thread" || (data?.my_bots || []).length > 1) && <span className="text-[10px] text-blue-200/70">{senderName}</span>}
                          {msgTime && <span className={`text-[10px] ${isSelf ? "text-blue-200/50" : "text-gray-600"}`}>{msgTime}</span>}
                        </div>
                        {hasImage && <img src={hasImage[1]} alt="" className="max-w-full max-h-48 rounded mb-1" />}
                        {textContent && <RenderContent content={textContent} threadMemberNames={target?.type === "thread" ? threadMemberNames : undefined} onMentionClick={handleMentionClick} />}
                      </div>
                    </div>
                  );
                })}
                {botTyping && <div className="flex justify-start"><div className="bg-gray-800 text-gray-400 rounded-lg px-3 py-2 text-sm"><span className="animate-pulse">正在输入...</span></div></div>}
                <div ref={messagesEndRef} />
              </div>

              {/* Image preview */}
              {pendingImage && <div className="px-4 py-2 border-t border-gray-800 flex items-center gap-2"><img src={pendingImage.preview} alt="" className="h-16 rounded" /><button onClick={cancelImage} className="text-xs text-red-400">✕</button></div>}

              {/* Bot identity selector for threads (only bots in this thread) */}
              {target?.type === "thread" && (() => {
                const myBotsInThread = (data?.my_bots || []).filter((b: { agent_name: string }) => threadMemberNames?.has(b.agent_name));
                return myBotsInThread.length > 1 ? (
                  <div className="px-4 py-1.5 border-t border-gray-800 flex items-center gap-2 text-xs text-gray-400">
                    <span>发言身份:</span>
                    <select value={threadBotId || myBotsInThread[0]?.instance_id || ""}
                      onChange={(e) => setThreadBotId(e.target.value)}
                      className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-200">
                      {myBotsInThread.map((b: { instance_id: string; agent_name: string }) => (
                        <option key={b.instance_id} value={b.instance_id}>{b.agent_name}</option>
                      ))}
                    </select>
                  </div>
                ) : null;
              })()}

              {/* Input */}
              <div className="px-4 py-3 border-t border-gray-800">
                <div className="flex items-center gap-2 relative">
                  <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleFileSelect} />
                  <input ref={generalFileRef} type="file" className="hidden" accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.md,.csv,.zip,.tar,.gz,.json,.xml,.mp3,.mp4,.wav,.jpg,.jpeg,.png,.gif,.webp" onChange={async (e) => {
                    const f = e.target.files?.[0]; if (!f) return; e.target.value = "";
                    try {
                      setUploading(true);
                      const result = await api.myOrgFileUpload(f);
                      const link = `📎 [${result.filename}](${result.url}) (${result.size_kb}KB)`;
                      setInput((v) => v ? v + "\n" + link : link);
                    } catch (err: unknown) { alert((err as Error).message || "上传失败"); }
                    finally { setUploading(false); }
                  }} />
                  <button onClick={() => fileInputRef.current?.click()} disabled={sending} className="shrink-0 p-2 text-gray-400 hover:text-gray-200 disabled:opacity-40" title="上传图片">
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0 0 22.5 18.75V5.25A2.25 2.25 0 0 0 20.25 3H3.75A2.25 2.25 0 0 0 1.5 5.25v13.5A2.25 2.25 0 0 0 3.75 21Zm16.5-13.5a1.125 1.125 0 1 1-2.25 0 1.125 1.125 0 0 1 2.25 0Z" /></svg>
                  </button>
                  <button onClick={() => generalFileRef.current?.click()} disabled={sending || uploading} className="shrink-0 p-2 text-gray-400 hover:text-gray-200 disabled:opacity-40" title="上传文件">
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M18.375 12.739l-7.693 7.693a4.5 4.5 0 01-6.364-6.364l10.94-10.94A3 3 0 1119.5 7.372L8.552 18.32m.009-.01l-.01.01m5.699-9.941l-7.81 7.81a1.5 1.5 0 002.112 2.13" /></svg>
                  </button>
                  <div className="relative">
                    <button onClick={() => setShowEmoji(!showEmoji)} className="shrink-0 p-2 text-gray-400 hover:text-gray-200" title="Emoji">😀</button>
                    {showEmoji && <EmojiPicker onSelect={(e) => setInput((v) => v + e)} onClose={() => setShowEmoji(false)} />}
                  </div>
                  <div className="relative flex-1">
                    {showMention && <MentionPopup members={allBots.map((b) => ({ name: b.name, online: b.online }))} filter={mentionFilter}
                      onSelect={handleMentionSelect} onClose={() => setShowMention(false)}
                      threadMembers={target?.type === "thread" ? threadMemberNames : undefined} />}
                    <textarea value={input} onChange={handleInputChange} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
                      onInput={(e) => { const el = e.currentTarget; el.style.height = "auto"; el.style.height = Math.min(el.scrollHeight, 120) + "px"; }}
                      rows={1}
                      placeholder={pendingImage ? "添加图片说明..." : t("chat.inputPlaceholder")} className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-blue-500 resize-none overflow-y-auto" style={{ maxHeight: 120 }} disabled={sending} />
                  </div>
                  <button onClick={handleSend} disabled={(!input.trim() && !pendingImage) || sending} className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm px-4 py-2 rounded-lg">
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
