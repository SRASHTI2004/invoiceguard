import { ReactNode } from "react";

// Tiny, safe Markdown renderer (bold, italic, `code`, bullet/numbered lists, headings, paragraphs).
// It builds React elements and never uses dangerouslySetInnerHTML, so any HTML in the text is shown as plain text.

const INLINE = /(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\*[^\s*][^*]*\*)/g;

function inline(text: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    if (/^\*\*[^*]+\*\*$/.test(part) || /^__[^_]+__$/.test(part)) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (/^`[^`]+`$/.test(part)) return <code key={i}>{part.slice(1, -1)}</code>;
    if (/^\*[^\s*][^*]*\*$/.test(part)) return <em key={i}>{part.slice(1, -1)}</em>;
    return part;
  });
}

const LIST_ITEM = /^\s*([*+-]|\d+[.)])\s+(.*)$/;
const HEADING = /^\s{0,3}#{1,6}\s+(.*)$/;

export default function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  const lines = text.split(/\r?\n/);
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    const first = LIST_ITEM.exec(line);
    if (first) {
      const ordered = /^\d/.test(first[1]);
      const items: ReactNode[] = [];
      while (i < lines.length) {
        const m = LIST_ITEM.exec(lines[i]);
        if (!m || /^\d/.test(m[1]) !== ordered) break;
        items.push(<li key={items.length}>{inline(m[2])}</li>);
        i++;
      }
      blocks.push(ordered ? <ol key={blocks.length}>{items}</ol> : <ul key={blocks.length}>{items}</ul>);
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      blocks.push(<p key={blocks.length}><strong>{inline(heading[1])}</strong></p>);
      i++;
      continue;
    }
    const para: ReactNode[] = [];
    while (i < lines.length && lines[i].trim() && !LIST_ITEM.test(lines[i]) && !HEADING.test(lines[i])) {
      if (para.length) para.push(<br key={`br${i}`} />);
      para.push(...inline(lines[i]));
      i++;
    }
    blocks.push(<p key={blocks.length}>{para}</p>);
  }
  return <div className="md">{blocks}</div>;
}
