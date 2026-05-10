'use client';

import { Fragment, useMemo, useState } from 'react';
import { Copy, Check } from 'lucide-react';

// ── Block types ─────────────────────────────────────────────────────────────

type TableRow = string[];

type Block =
  | { type: 'h'; level: 1 | 2 | 3; text: string }
  | { type: 'p'; text: string }
  | { type: 'ul'; items: string[] }
  | { type: 'ol'; items: string[] }
  | { type: 'code'; lang: string; text: string }
  | { type: 'blockquote'; text: string }
  | { type: 'table'; headers: TableRow; rows: TableRow[] }
  | { type: 'hr' };

function parseTableLine(line: string): string[] {
  return line
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((c) => c.trim());
}

function isSeparatorRow(cells: string[]): boolean {
  return cells.every((c) => /^:?-+:?$/.test(c));
}

export function parseBlocks(src: string): Block[] {
  const lines = src.replace(/\r\n/g, '\n').split('\n');
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];

    // fenced code
    if (/^```/.test(line)) {
      const lang = line.slice(3).trim();
      const buf: string[] = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) { buf.push(lines[i]); i++; }
      if (i < lines.length) i++;
      blocks.push({ type: 'code', lang, text: buf.join('\n') });
      continue;
    }

    // headings
    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    if (h) {
      blocks.push({ type: 'h', level: h[1].length as 1 | 2 | 3, text: h[2].trim() });
      i++;
      continue;
    }

    // horizontal rule
    if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      blocks.push({ type: 'hr' });
      i++;
      continue;
    }

    // blockquote
    if (/^\s*>\s*/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*>\s*/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*>\s*/, ''));
        i++;
      }
      blocks.push({ type: 'blockquote', text: items.join(' ') });
      continue;
    }

    // table — header row must start with | and next non-blank line must be separator
    if (/^\|/.test(line) && i + 1 < lines.length) {
      const headerCells = parseTableLine(line);
      const sepLine = lines[i + 1];
      const sepCells = /^\|/.test(sepLine) ? parseTableLine(sepLine) : [];
      if (sepCells.length > 0 && isSeparatorRow(sepCells)) {
        i += 2; // skip header + separator
        const rows: TableRow[] = [];
        while (i < lines.length && /^\|/.test(lines[i])) {
          rows.push(parseTableLine(lines[i]));
          i++;
        }
        blocks.push({ type: 'table', headers: headerCells, rows });
        continue;
      }
    }

    // bullets
    if (/^\s*[-*•]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*•]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*•]\s+/, ''));
        i++;
      }
      blocks.push({ type: 'ul', items });
      continue;
    }

    // ordered list
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+\.\s+/, ''));
        i++;
      }
      blocks.push({ type: 'ol', items });
      continue;
    }

    // blank
    if (line.trim() === '') { i++; continue; }

    // paragraph (consume until blank or structural element)
    const buf: string[] = [line];
    i++;
    while (
      i < lines.length &&
      lines[i].trim() !== '' &&
      !/^(#{1,3})\s+/.test(lines[i]) &&
      !/^\s*[-*•]\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i]) &&
      !/^```/.test(lines[i]) &&
      !/^\s*>\s*/.test(lines[i]) &&
      !/^\|/.test(lines[i]) &&
      !/^(-{3,}|\*{3,}|_{3,})\s*$/.test(lines[i])
    ) {
      buf.push(lines[i]);
      i++;
    }
    blocks.push({ type: 'p', text: buf.join(' ') });
  }
  return blocks;
}

// ── Inline renderer ──────────────────────────────────────────────────────────

type Token = { type: 'text' | 'code' | 'bold' | 'italic' | 'link'; value: string; href?: string };

export function renderInline(text: string, keyBase: string): React.ReactNode {
  const tokens: Token[] = [];

  const consume = (re: RegExp, kind: Token['type']) => {
    const out: Token[] = [];
    for (const tok of tokens.length ? tokens : [{ type: 'text', value: text } as Token]) {
      if (tok.type !== 'text') { out.push(tok); continue; }
      const s = tok.value;
      let m: RegExpExecArray | null;
      let last = 0;
      const localRe = new RegExp(re.source, re.flags);
      while ((m = localRe.exec(s)) !== null) {
        if (m.index > last) out.push({ type: 'text', value: s.slice(last, m.index) });
        if (kind === 'link') out.push({ type: 'link', value: m[1], href: m[2] });
        else                  out.push({ type: kind, value: m[1] });
        last = m.index + m[0].length;
      }
      if (last < s.length) out.push({ type: 'text', value: s.slice(last) });
    }
    tokens.length = 0;
    tokens.push(...out);
  };

  consume(/\[([^\]]+)\]\(([^)]+)\)/g, 'link');
  consume(/`([^`]+)`/g, 'code');
  consume(/\*\*([^*]+)\*\*/g, 'bold');
  consume(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, 'italic');

  return (
    <>
      {tokens.map((t, idx) => {
        const k = `${keyBase}-${idx}`;
        if (t.type === 'code')   return <code key={k} className="rounded bg-[var(--metis-code-bg)] px-1.5 py-0.5 text-[0.85em] text-[var(--metis-code-fg)]">{t.value}</code>;
        if (t.type === 'bold')   return <strong key={k} className="font-semibold">{t.value}</strong>;
        if (t.type === 'italic') return <em key={k} className="italic">{t.value}</em>;
        if (t.type === 'link')   return <a key={k} href={t.href} target="_blank" rel="noreferrer noopener" className="text-violet-400 underline-offset-2 hover:underline">{t.value}</a>;
        return <Fragment key={k}>{t.value}</Fragment>;
      })}
    </>
  );
}

// ── Code block with copy button ──────────────────────────────────────────────

export function CodeBlock({ lang, text }: { lang: string; text: string }) {
  const [copied, setCopied] = useState(false);
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {}
  };
  const lineCount = text.split('\n').length;
  return (
    <div className="metis-code-block group overflow-hidden rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)]">
      <div className="flex items-center gap-2 border-b border-[var(--metis-border)] bg-[var(--metis-elevated)] px-3 py-1.5">
        <span className="text-[10px] uppercase tracking-widest text-[var(--metis-fg-dim)]">
          {lang || 'code'}
        </span>
        <span className="text-[10px] text-[var(--metis-fg-dim)]">·</span>
        <span className="text-[10px] text-[var(--metis-fg-dim)]">{lineCount} {lineCount === 1 ? 'line' : 'lines'}</span>
        <button
          type="button"
          onClick={onCopy}
          className="ml-auto inline-flex items-center gap-1 rounded-md border border-[var(--metis-border)] bg-[var(--metis-bg)] px-1.5 py-0.5 text-[10px] text-[var(--metis-fg-muted)] transition hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]"
          title="Copy code"
        >
          {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="overflow-x-auto p-3.5 text-[12.5px] leading-6 text-[var(--metis-fg)]">
        <code className="font-mono">{text}</code>
      </pre>
    </div>
  );
}

// ── Table ────────────────────────────────────────────────────────────────────

function TableBlock({ headers, rows }: { headers: TableRow; rows: TableRow[] }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-[var(--metis-border)]">
      <table className="min-w-full text-[13px]">
        <thead className="bg-[var(--metis-elevated)]">
          <tr>
            {headers.map((h, i) => (
              <th
                key={i}
                className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wider text-[var(--metis-fg-muted)] border-b border-[var(--metis-border)]"
              >
                {renderInline(h, `th-${i}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr
              key={ri}
              className={ri % 2 === 0 ? 'bg-transparent' : 'bg-[var(--metis-elevated)]/40'}
            >
              {row.map((cell, ci) => (
                <td
                  key={ci}
                  className="px-3 py-2 text-[var(--metis-fg)] border-b border-[var(--metis-border)] last:border-b-0"
                >
                  {renderInline(cell, `td-${ri}-${ci}`)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Main MarkdownView ────────────────────────────────────────────────────────

export default function MarkdownView({ source }: { source: string }) {
  const blocks = useMemo(() => parseBlocks(source), [source]);
  return (
    <div className="space-y-4 text-[15px] leading-7 text-[var(--metis-fg)]">
      {blocks.map((b, idx) => {
        const k = `b-${idx}`;
        if (b.type === 'h') {
          const Tag: 'h1' | 'h2' | 'h3' = (`h${b.level}` as 'h1' | 'h2' | 'h3');
          const cls =
            b.level === 1 ? 'text-2xl font-semibold tracking-tight text-[var(--metis-foreground)]' :
            b.level === 2 ? 'mt-2 text-xl font-semibold tracking-tight text-[var(--metis-foreground)]' :
                            'mt-1 text-base font-semibold text-[var(--metis-foreground)]';
          return <Tag key={k} className={cls}>{renderInline(b.text, k)}</Tag>;
        }
        if (b.type === 'p')   return <p key={k} className="text-[var(--metis-fg)]">{renderInline(b.text, k)}</p>;
        if (b.type === 'blockquote') return (
          <blockquote key={k} className="border-l-2 border-violet-500/50 pl-3 text-[var(--metis-fg-muted)] italic">
            {renderInline(b.text, k)}
          </blockquote>
        );
        if (b.type === 'ul')  return (
          <ul key={k} className="ml-5 list-disc space-y-1.5">
            {b.items.map((it, j) => <li key={`${k}-${j}`}>{renderInline(it, `${k}-${j}`)}</li>)}
          </ul>
        );
        if (b.type === 'ol')  return (
          <ol key={k} className="ml-5 list-decimal space-y-1.5">
            {b.items.map((it, j) => <li key={`${k}-${j}`}>{renderInline(it, `${k}-${j}`)}</li>)}
          </ol>
        );
        if (b.type === 'table') return (
          <TableBlock key={k} headers={(b as { type: 'table'; headers: TableRow; rows: TableRow[] }).headers} rows={(b as { type: 'table'; headers: TableRow; rows: TableRow[] }).rows} />
        );
        if (b.type === 'hr') return (
          <hr key={k} className="border-[var(--metis-border)]" />
        );
        return <CodeBlock key={k} lang={(b as { type: 'code'; lang: string; text: string }).lang} text={(b as { type: 'code'; lang: string; text: string }).text} />;
      })}
    </div>
  );
}
