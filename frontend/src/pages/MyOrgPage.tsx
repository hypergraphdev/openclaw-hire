import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useT } from "../contexts/LanguageContext";
import type { ChatInfo, ChatMessage, MyOrgData, MyOrgPeer } from "../types";

const EMOJI_LIST = ["😀","😂","🤣","😊","😍","🥰","😘","😎","🤔","😅","😢","😭","😤","🔥","❤️","👍","👎","👋","🎉","🙏","💯","✨","⭐","🚀","💡","📎","✅","❌","⚡","🌟"];

function OnlineDot({ online }: { online: boolean }) {
  return <span className={`inline-block h-2 w-2 rounded-full ${online ? "bg-green-400" : "bg-gray-500"}`} />;
}

function EmojiPicker({ onSelect, onClose }: { onSelect: (e: string) => void; onClose: () => void }) {
  return (
    <div className="absolute bottom-12 left-0 bg-gray-800 border border-gray-700 rounded-lg p-2 shadow-xl z-50">
      <div className="grid grid-cols-10 gap-1">
        {EMOJI_LIST.map((e) => (
          <button key={e} onClick={() => { onSelect(e); onClose(); }}
            className="w-8 h-8 flex items-center justify-center text-lg hover:bg-gray-700 rounded">{e}</button>
        ))}
      </div>
    </div>
  );
}

export function MyOrgPage() {
  const t = useT();
  const [data, setData] = useState<MyOrgData | null>(null);
  const [loading, setLoading] = useState(true);

  // Chat state
  const [selectedBot, setSelectedBot] = useState<MyOrgPeer | null>(null);
  const [chatInfo, setChatInfo] = useState<ChatInfo | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
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

  const wsRef = useRef<WebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const myBotIdRef = useRef("");
  const typingTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const userScrolledUp = useRef(false);

  useEffect(() => {
    api.myOrg().then(setData).finally(() => setLoading(false));
  }, []);

  // Sort messages by created_at ascending
  function sortMessages(msgs: ChatMessage[]) {
    return [...msgs].sort((a, b) => (a.created_at || 0) - (b.created_at || 0));
  }

  // Select bot → load chat info
  const selectBot = useCallback(async (bot: MyOrgPeer) => {
    setSelectedBot(bot);
    setMessages([]);
    setChannelId(null);
    setChatInfo(null);
    setBotTyping(false);
    setPendingImage(null);
    setShowEmoji(false);
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
    } catch {
      // Chat info failed
    }
  }, []);

  // WebSocket
  useEffect(() => {
    if (!selectedBot || !chatInfo) return;
    let mounted = true;

    async function connect() {
      setWsStatus("connecting");
      try {
        const { ticket, ws_url } = await api.myOrgChatWsTicket(selectedBot!.name);
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
            const data = JSON.parse(ev.data);
            if (data.type === "typing") {
              setBotTyping(true);
              clearTimeout(typingTimer.current);
              typingTimer.current = setTimeout(() => setBotTyping(false), 5000);
              return;
            }
            if (data.type === "message" && data.message) {
              const msg: ChatMessage = data.message;
              if (msg.sender_id !== myBotIdRef.current) {
                setBotTyping(false);
                clearTimeout(typingTimer.current);
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
          } catch { /* ignore */ }
        };
      } catch {
        mounted && setWsStatus("disconnected");
      }
    }

    connect();
    return () => {
      mounted = false;
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [selectedBot?.bot_id, chatInfo?.admin_bot_id]);

  // Auto scroll on initial load
  useEffect(() => {
    if (!userScrolledUp.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages.length]);

  function handleScroll() {
    const el = containerRef.current;
    if (!el) return;
    userScrolledUp.current = el.scrollHeight - el.scrollTop - el.clientHeight > 100;
  }

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const preview = URL.createObjectURL(file);
    setPendingImage({ file, preview });
    e.target.value = "";
  }

  function cancelImage() {
    if (pendingImage) {
      URL.revokeObjectURL(pendingImage.preview);
      setPendingImage(null);
    }
  }

  async function handleSend() {
    if ((!input.trim() && !pendingImage) || !selectedBot || sending) return;
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
      const result = await api.myOrgChatSend(selectedBot.name, input.trim(), imageUrl);
      if (result.channel_id && !channelId) setChannelId(result.channel_id);
      setMessages((prev) => {
        if (prev.some((m) => m.id === result.message.id)) return prev;
        return sortMessages([...prev, result.message]);
      });
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
    if (!channelId || !selectedBot || messages.length === 0) return;
    const oldest = messages[0];
    try {
      const hist = await api.myOrgChatMessages(channelId, selectedBot.name, oldest.id);
      setMessages((prev) => sortMessages([...hist.messages, ...prev]));
      setHasMore(hist.has_more);
    } catch { /* ignore */ }
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

  return (
    <div className="h-[calc(100vh-80px)] flex flex-col">
      <div className="px-4 py-3 border-b border-gray-800">
        <h1 className="text-lg font-semibold text-white">{t("myOrg.title")}: {data.org_name}</h1>
        {data.is_default_org && (
          <div className="mt-2 px-3 py-2 bg-yellow-900/30 border border-yellow-700 rounded text-yellow-300 text-xs">
            ⚠ {t("myOrg.defaultOrgWarning")}
          </div>
        )}
      </div>

      <div className="flex flex-1 min-h-0">
        {/* Bot list */}
        <div className="w-64 border-r border-gray-800 overflow-auto p-3 space-y-1">
          <h3 className="text-xs text-gray-500 mb-2">{t("myOrg.botList")} ({allBots.length})</h3>
          {allBots.map((bot) => (
            <button key={bot.bot_id} onClick={() => selectBot(bot)}
              className={`w-full text-left px-3 py-2 rounded-md transition-colors flex items-center gap-2 ${
                selectedBot?.bot_id === bot.bot_id ? "bg-blue-600/20 border border-blue-600" : "hover:bg-gray-800 border border-transparent"
              }`}>
              <OnlineDot online={bot.online} />
              <span className="text-sm text-gray-200 truncate flex-1">{bot.name}</span>
              {bot.is_mine && <span className="text-[10px] px-1 py-0.5 rounded bg-blue-600/30 text-blue-400">{t("myOrg.mine")}</span>}
            </button>
          ))}
        </div>

        {/* Chat area */}
        <div className="flex-1 flex flex-col min-w-0">
          {!selectedBot ? (
            <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">{t("myOrg.selectBot")}</div>
          ) : (
            <>
              {/* Header */}
              <div className="px-4 py-2 border-b border-gray-800 flex items-center gap-2">
                <OnlineDot online={selectedBot.online} />
                <span className="text-sm font-medium text-white">{selectedBot.name}</span>
                {selectedBot.is_mine && <span className="text-[10px] px-1 py-0.5 rounded bg-blue-600/30 text-blue-400">{t("myOrg.mine")}</span>}
                <span className={`ml-auto text-[10px] ${wsStatus === "connected" ? "text-green-400" : wsStatus === "connecting" ? "text-yellow-400" : "text-gray-500"}`}>
                  {wsStatus === "connected" ? t("chat.connected") : wsStatus === "connecting" ? t("chat.connecting") : t("chat.disconnected")}
                </span>
              </div>

              {/* Messages */}
              <div ref={containerRef} onScroll={handleScroll} className="flex-1 overflow-auto px-4 py-3 space-y-2">
                {hasMore && (
                  <button onClick={loadMore} className="text-xs text-blue-400 hover:text-blue-300 block mx-auto mb-2">{t("chat.loadMore")}</button>
                )}
                {messages.length === 0 && !botTyping && (
                  <div className="text-center text-gray-500 text-sm py-8">{t("chat.noMessages")}</div>
                )}
                {messages.map((msg) => {
                  const isSelf = msg.sender_id === myBotId;
                  const hasImage = msg.content?.match(/\[(?:image|图片)\]\((https?:\/\/[^\s)]+)\)/);
                  const textContent = msg.content?.replace(/\[(?:image|图片)\]\(https?:\/\/[^\s)]+\)\n?/, "").trim();
                  return (
                    <div key={msg.id} className={`flex ${isSelf ? "justify-end" : "justify-start"}`}>
                      <div className={`max-w-[75%] rounded-lg px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap break-words ${
                        isSelf ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-200"
                      }`}>
                        {!isSelf && <div className="text-[10px] text-gray-400 mb-0.5">{msg.sender_name}</div>}
                        {hasImage && <img src={hasImage[1]} alt="" className="max-w-full max-h-48 rounded mb-1" />}
                        {textContent}
                      </div>
                    </div>
                  );
                })}
                {botTyping && (
                  <div className="flex justify-start">
                    <div className="bg-gray-800 text-gray-400 rounded-lg px-3 py-2 text-sm">
                      <span className="animate-pulse">正在输入...</span>
                    </div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>

              {/* Image preview */}
              {pendingImage && (
                <div className="px-4 py-2 border-t border-gray-800 flex items-center gap-2">
                  <img src={pendingImage.preview} alt="" className="h-16 rounded" />
                  <button onClick={cancelImage} className="text-xs text-red-400 hover:text-red-300">✕ 取消</button>
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
                    <button onClick={() => setShowEmoji(!showEmoji)} className="shrink-0 p-2 text-gray-400 hover:text-gray-200" title="Emoji">
                      😀
                    </button>
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
