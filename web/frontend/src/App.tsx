import Box from "@mui/material/Box";
import Drawer from "@mui/material/Drawer";
import IconButton from "@mui/material/IconButton";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import ViewSidebarOutlinedIcon from "@mui/icons-material/ViewSidebarOutlined";
import { Composer } from "./components/Composer";
import { MessageList } from "./components/MessageList";
import { SidePanel } from "./components/SidePanel";
import { useChatSession } from "./hooks/useChatSession";
import { useSidePanelOpen } from "./hooks/useSidePanelOpen";

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

  const { open: sideOpen, toggle: toggleSide, setOpen: setSideOpen, isDesktop } =
    useSidePanelOpen();

  const sidePanel = (
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
  );

  return (
    <Box
      sx={{
        maxWidth: sideOpen && isDesktop ? 1100 : 900,
        mx: "auto",
        height: "100%",
        p: { xs: 1.5, sm: 2 },
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
        transition: "max-width 0.2s ease",
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
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="h1" sx={{ fontSize: "1.55rem", m: 0 }}>
            Зипка
          </Typography>
        </Box>
        <Tooltip title={sideOpen ? "Скрыть панель" : "Показать панель"} arrow>
          <IconButton
            aria-label={sideOpen ? "Скрыть панель" : "Показать панель"}
            aria-pressed={sideOpen}
            onClick={toggleSide}
            size="small"
            sx={{
              border: 1,
              borderColor: sideOpen ? "primary.main" : "divider",
              bgcolor: sideOpen ? "rgba(200, 240, 122, 0.12)" : "#24332c",
              color: sideOpen ? "primary.main" : "text.primary",
              "&:hover": {
                bgcolor: sideOpen ? "rgba(200, 240, 122, 0.2)" : "#2c3d34",
                borderColor: sideOpen ? "primary.main" : "divider",
              },
            }}
          >
            <ViewSidebarOutlinedIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Stack>

      <Box
        sx={{
          flex: 1,
          minHeight: 0,
          display: "grid",
          gridTemplateColumns: {
            xs: "1fr",
            md: sideOpen ? "1.5fr 0.9fr" : "1fr",
          },
          gap: 2,
          transition: "grid-template-columns 0.2s ease",
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
            height: "100%",
            minHeight: { xs: "min(70vh, 640px)", md: 0 },
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

        {isDesktop && sideOpen ? (
          <Paper
            elevation={0}
            sx={{
              border: 1,
              borderColor: "divider",
              minHeight: 0,
              overflow: "hidden",
              display: "flex",
              flexDirection: "column",
            }}
          >
            {sidePanel}
          </Paper>
        ) : null}
      </Box>

      {!isDesktop ? (
        <Drawer
          anchor="right"
          open={sideOpen}
          onClose={() => setSideOpen(false)}
          slotProps={{
            paper: {
              sx: {
                width: "100%",
                maxWidth: "100vw",
                bgcolor: "#17201c",
                backgroundImage: "none",
                borderLeft: 1,
                borderColor: "divider",
              },
            },
          }}
        >
          <Box
            sx={{
              height: "100%",
              display: "flex",
              flexDirection: "column",
              minHeight: 0,
              overflow: "hidden",
            }}
          >
            <Stack
              direction="row"
              spacing={1}
              sx={{
                px: 2,
                py: 1.25,
                alignItems: "center",
                borderBottom: 1,
                borderColor: "divider",
                flexShrink: 0,
              }}
            >
              <Typography
                variant="subtitle2"
                sx={{ flex: 1, fontWeight: 700, color: "text.secondary" }}
              >
                Панель
              </Typography>
              <IconButton
                aria-label="Закрыть панель"
                size="small"
                onClick={() => setSideOpen(false)}
                sx={{ color: "text.secondary" }}
              >
                <ViewSidebarOutlinedIcon fontSize="small" />
              </IconButton>
            </Stack>
            <Box sx={{ flex: 1, minHeight: 0, overflow: "hidden" }}>{sidePanel}</Box>
          </Box>
        </Drawer>
      ) : null}
    </Box>
  );
}
