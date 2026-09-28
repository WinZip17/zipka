import { createTheme } from "@mui/material/styles";

export const theme = createTheme({
  palette: {
    mode: "dark",
    primary: {
      main: "#c8f07a",
      contrastText: "#132016",
    },
    secondary: {
      main: "#7ec8a3",
    },
    warning: {
      main: "#ffb454",
      contrastText: "#1a1408",
    },
    error: {
      main: "#e57373",
    },
    background: {
      default: "#0f1412",
      paper: "rgba(23, 32, 28, 0.92)",
    },
    text: {
      primary: "#e7f0ea",
      secondary: "#8aa193",
    },
    divider: "rgba(231, 240, 234, 0.12)",
  },
  typography: {
    fontFamily: '"IBM Plex Sans", "Manrope", sans-serif',
    h1: {
      fontFamily: '"Manrope", sans-serif',
      fontWeight: 800,
      letterSpacing: "0.02em",
    },
    h2: {
      fontFamily: '"Manrope", sans-serif',
      fontWeight: 700,
    },
    button: {
      textTransform: "none",
      fontWeight: 700,
    },
  },
  shape: {
    borderRadius: 12,
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        html: { height: "100%" },
        body: {
          height: "100%",
          margin: 0,
          overflow: "hidden",
          background:
            "radial-gradient(1200px 600px at 10% -10%, #24352c 0%, transparent 55%)," +
            "radial-gradient(900px 500px at 100% 0%, #1a2a38 0%, transparent 50%)," +
            "linear-gradient(160deg, #0f1412, #121816 40%, #0c1014)",
        },
        "#root": { height: "100%" },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: "none",
          backdropFilter: "blur(8px)",
        },
      },
    },
    MuiButton: {
      defaultProps: {
        disableElevation: true,
      },
      styleOverrides: {
        root: {
          borderRadius: 10,
        },
        contained: {
          "&.MuiButton-colorPrimary:hover": { filter: "brightness(1.05)" },
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          borderRadius: 10,
        },
      },
    },
  },
});
