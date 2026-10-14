import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import { parseFencedCode } from "../../chat/parseFencedCode";
import { CodeBlock } from "./CodeBlock";

type Props = {
  text: string;
};

export function MessageContent({ text }: Props) {
  const segments = parseFencedCode(text);
  const first = segments[0];
  if (segments.length === 1 && first?.type === "text") {
    return (
      <Typography
        component="div"
        variant="body2"
        sx={{ color: "text.primary", whiteSpace: "pre-wrap" }}
      >
        {first.text}
      </Typography>
    );
  }

  return (
    <Box sx={{ color: "text.primary", fontSize: "0.875rem", lineHeight: 1.45 }}>
      {segments.map((seg, i) => {
        if (seg.type === "code") {
          return <CodeBlock key={`c-${i}`} lang={seg.lang} code={seg.code} />;
        }
        if (!seg.text) return null;
        // не раздувать вертикальные отступы вокруг fence: крайние \n часто артефакт
        const trimmed = seg.text.replace(/^\n+/, "").replace(/\n+$/, "\n");
        if (!trimmed) return null;
        return (
          <Typography
            key={`t-${i}`}
            component="div"
            variant="body2"
            sx={{ color: "text.primary", whiteSpace: "pre-wrap" }}
          >
            {trimmed}
          </Typography>
        );
      })}
    </Box>
  );
}
