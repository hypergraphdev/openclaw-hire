import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useT } from "../contexts/LanguageContext";
import type { ChatInfo, ChatMessage, MyOrgData, MyOrgPeer } from "../types";

function OnlineDot({ online }: { online: boolean }) {
  return <span className={`inline-block h-2 w-2 rounded-full ${online ? "bg-green-400" : "bg-gray-500"}`} />;
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
  const wsRef = useRef<WebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const myBotIdRef = useRef("");

  useEffect(() => {
    api.myOrg().then(setData).finally(() => setLoading(false));
  }, []);

  // Select bot → load chat info
  const selectBot = useCallback(async (bot: MyOrgPeer) => {
    setSelectedBot(bot);
    setMessages([]);
    setChannelId(null);
    setChatInfo(null);
    try {
      const info = await api.myOrgChatInfo(bot.name);
      setChatInfo(info);
      myBotIdRef.current = info.admin_bot_id;
      if (info.dm_channel_id) {
        setChannelId(info.dm_channel_id);
        const hist = await api.myOrgChatMessages(info.dm_channel_id, bot.name);
        setMessages(hist.messages.reverse());
        setHasMore(hist.has_more);
      }
    } catch {
      // Chat info failed
    }
  }, []);

  // WebSocket
  useEffect(() => {
    if (!selectedBot || !chatInfo) return;
    let ws: WebSocket;
    let mounted = true;

    async function connect() {
      setWsStatus("connecting");
      try {
        const { ticket, ws_url } = await api.myOrgChatWsTicket(selectedBot!.name);
        ws = new WebSocket(`${ws_url}?ticket=${ticket}`);
        wsRef.current = ws;

        ws.onopen = () => mounted && setWsStatus("connected");
        ws.onclose = () => {
          if (!mounted) return;
          setWsStatus("disconnected");
          setTimeout(() => mounted && connect(), 3000);
        };
        ws.onmessage = (ev) => {
          try {
            const data = JSON.parse(ev.data);
            if (data.type === "message" && data.message) {
              const msg = data.message;
              setMessages((prev) => {
                if (prev.some((m) => m.id === msg.id)) return prev;
                return [...prev, msg];
              });
              if (!channelId && msg.channel_id) {
                setChannelId(msg.channel_id);
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
    };
  }, [selectedBot?.bot_id, chatInfo?.admin_bot_id]);

  // Auto scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  // Send message
  async function handleSend() {
    if (!input.trim() || !selectedBot || sending) return;
    const content = input.trim();
    setInput("");
    setSending(true);
    try {
      const result = await api.myOrgChatSend(selectedBot.name, content);
      if (result.channel_id && !channelId) setChannelId(result.channel_id);
      setMessages((prev) => {
        if (prev.some((m) => m.id === result.message.id)) return prev;
        return [...prev, result.message];
      });
    } catch {
      setInput(content); // Restore on failure
    }
    setSending(false);
  }

  // Load more
  async function loadMore() {
    if (!channelId || !selectedBot || messages.length === 0) return;
    const oldest = messages[0];
    try {
      const hist = await api.myOrgChatMessages(channelId, selectedBot.name, oldest.id);
      setMessages((prev) => [...hist.messages.reverse(), ...prev]);
      setHasMore(hist.has_more);
    } catch { /* ignore */ }
  }

  if (loading) return <div className="text-gray-400 text-sm p-6">{t("common.loading")}</div>;

  // Status pages
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
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-800">
        <h1 className="text-lg font-semibold text-white">{t("myOrg.title")}: {data.org_name}</h1>
        {data.is_default_org && (
          <div className="mt-2 px-3 py-2 bg-yellow-900/30 border border-yellow-700 rounded text-yellow-300 text-xs">
            ⚠ {t("myOrg.defaultOrgWarning")}
          </div>
        )}
      </div>

      {/* Main layout */}
      <div className="flex flex-1 min-h-0">
        {/* Bot list */}
        <div className="w-64 border-r border-gray-800 overflow-auto p-3 space-y-1">
          <h3 className="text-xs text-gray-500 mb-2">{t("myOrg.botList")} ({allBots.length})</h3>
          {allBots.map((bot) => (
            <button
              key={bot.bot_id}
              onClick={() => selectBot(bot)}
              className={`w-full text-left px-3 py-2 rounded-md transition-colors flex items-center gap-2 ${
                selectedBot?.bot_id === bot.bot_id ? "bg-blue-600/20 border border-blue-600" : "hover:bg-gray-800 border border-transparent"
              }`}
            >
              <OnlineDot online={bot.online} />
              <span className="text-sm text-gray-200 truncate flex-1">{bot.name}</span>
              {bot.is_mine && (
                <span className="text-[10px] px-1 py-0.5 rounded bg-blue-600/30 text-blue-400">{t("myOrg.mine")}</span>
              )}
            </button>
          ))}
        </div>

        {/* Chat area */}
        <div className="flex-1 flex flex-col min-w-0">
          {!selectedBot ? (
            <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">
              {t("myOrg.selectBot")}
            </div>
          ) : (
            <>
              {/* Chat header */}
              <div className="px-4 py-2 border-b border-gray-800 flex items-center gap-2">
                <OnlineDot online={selectedBot.online} />
                <span className="text-sm font-medium text-white">{selectedBot.name}</span>
                {selectedBot.is_mine && (
                  <span className="text-[10px] px-1 py-0.5 rounded bg-blue-600/30 text-blue-400">{t("myOrg.mine")}</span>
                )}
                <span className={`ml-auto text-[10px] ${wsStatus === "connected" ? "text-green-400" : wsStatus === "connecting" ? "text-yellow-400" : "text-gray-500"}`}>
                  {wsStatus === "connected" ? t("chat.connected") : wsStatus === "connecting" ? t("chat.connecting") : t("chat.disconnected")}
                </span>
              </div>

              {/* Messages */}
              <div ref={containerRef} className="flex-1 overflow-auto px-4 py-3 space-y-2">
                {hasMore && (
                  <button onClick={loadMore} className="text-xs text-blue-400 hover:text-blue-300 block mx-auto mb-2">
                    {t("chat.loadMore")}
                  </button>
                )}
                {messages.length === 0 && (
                  <div className="text-center text-gray-500 text-sm py-8">{t("chat.noMessages")}</div>
                )}
                {messages.map((msg) => {
                  const isSelf = msg.sender_id === myBotId;
                  return (
                    <div key={msg.id} className={`flex ${isSelf ? "justify-end" : "justify-start"}`}>
                      <div className={`max-w-[75%] rounded-lg px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap break-words ${
                        isSelf ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-200"
                      }`}>
                        {!isSelf && <div className="text-[10px] text-gray-400 mb-0.5">{msg.sender_name}</div>}
                        {msg.content}
                      </div>
                    </div>
                  );
                })}
                <div ref={messagesEndRef} />
              </div>

              {/* Input */}
              <div className="px-4 py-3 border-t border-gray-800 flex gap-2">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
                  placeholder={t("chat.inputPlaceholder")}
                  className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-blue-500"
                />
                <button
                  onClick={handleSend}
                  disabled={sending || !input.trim()}
                  className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm px-4 py-2 rounded-lg"
                >
                  {sending ? t("chat.sending") : t("chat.send")}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
