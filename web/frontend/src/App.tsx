import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { Composer } from "./components/Composer";
import { MessageList } from "./components/MessageList";
import { SidePanel } from "./components/SidePanel";
import { useChatSession } from "./hooks/useChatSession";

export default function App() {
  const {
    messages,
    status,
    pending,
    stagedFile,
    setStagedFile,
    archiveMember,
    setArchiveMember,
    busy,
    thinking,
    setThinking,
    newsThinking,
    dropActive,
    setDropActive,
    hasMore,
    loadingOlder,
    replyTo,
    setReplyTo,
    finetuneBusy,
    addBubble,
    refreshStatus,
    loadOlderHistory,
    onBusyFromPanel,
    onSend,
    resetChat,
  } = useChatSession();

  return (
    <Box
      sx={{
        maxWidth: 1100,
        mx: "auto",
        height: "100%",
        p: { xs: 1.5, sm: 2 },
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
      }}
    >
      <Stack
        direction="row"
        spacing={1.5}
        sx={{ mb: 1.5, flexShrink: 0, alignItems: "center" }}
      >
        <Box
          sx={{
            width: 44,
            height: 44,
            borderRadius: 3,
            display: "grid",
            placeItems: "center",
            background: "linear-gradient(145deg, #d9ff8a, #7ec8a3)",
            color: "#102018",
            fontWeight: 800,
            fontSize: "1.2rem",
            fontFamily: '"Manrope", sans-serif',
          }}
        >
          Z
        </Box>
        <Box>
          <Typography variant="h1" sx={{ fontSize: "1.55rem", m: 0 }}>
            Зипка
          </Typography>
        </Box>
      </Stack>

      <Box
        sx={{
          flex: 1,
          minHeight: 0,
          display: "grid",
          gridTemplateColumns: { xs: "1fr", md: "1.5fr 0.9fr" },
          gap: 2,
        }}
      >
        <Paper
          elevation={0}
          onDragOver={(e) => {
            e.preventDefault();
            setDropActive(true);
          }}
          onDragLeave={() => setDropActive(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDropActive(false);
            const file = e.dataTransfer.files?.[0];
            if (file) setStagedFile(file);
          }}
          sx={{
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
            height: { xs: "min(70vh, 640px)", md: "100%" },
            border: 1,
            borderColor: dropActive ? "primary.main" : "divider",
            outline: dropActive ? "2px dashed" : "none",
            outlineColor: "primary.main",
            outlineOffset: -4,
          }}
        >
          <MessageList
            messages={messages}
            hasMore={hasMore}
            loadingOlder={loadingOlder}
            onLoadOlder={() => void loadOlderHistory()}
            thinking={
              finetuneBusy
                ? "Идёт дообучение…"
                : thinking || (!busy ? newsThinking : null)
            }
            onReply={(b) => setReplyTo(b)}
          />
          <Composer
            disabled={busy || finetuneBusy}
            stagedFile={stagedFile}
            onStageFile={setStagedFile}
            onSend={(msg) => void onSend(msg)}
            replyTo={replyTo}
            onClearReply={() => setReplyTo(null)}
          />
        </Paper>

        <Paper
          elevation={0}
          sx={{
            border: 1,
            borderColor: "divider",
            minHeight: 0,
            overflow: "hidden",
          }}
        >
          <SidePanel
            status={status}
            pending={pending}
            busy={busy}
            eyesOn={!!status?.eyes}
            earsOn={!!status?.ears}
            archiveMember={archiveMember}
            onArchiveMember={setArchiveMember}
            onBubble={addBubble}
            onThinking={setThinking}
            onBusy={onBusyFromPanel}
            onRefresh={() => void refreshStatus()}
            onResetChat={resetChat}
            onStageFile={setStagedFile}
          />
        </Paper>
      </Box>
    </Box>
  );
}
