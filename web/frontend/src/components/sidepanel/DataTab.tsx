import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";

type Props = {
  busy: boolean;
  onReset: () => void;
};

export function DataTab({ busy, onReset }: Props) {
  return (
    <Box>
      <Alert severity="warning" sx={{ mb: 1.5 }}>
        Полный сброс чата, заметок, целей, книг, новостей, патчей и persona.yaml.
        Действие необратимо.
      </Alert>
      <Button
        fullWidth
        color="error"
        variant="contained"
        disabled={busy}
        onClick={() => void onReset()}
        sx={{ bgcolor: "#5a1f1f", "&:hover": { bgcolor: "#6e2828" } }}
      >
        Сброс обучения
      </Button>
    </Box>
  );
}
