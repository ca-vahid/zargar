import { useCallback, useState } from "react";
import { Markdown } from "../components/technique/Markdown";
import method from "../../../docs/techniques/options-cartel/METHOD.md?raw";
import rules from "../../../docs/techniques/options-cartel/TRADING-RULES.md?raw";
import sources from "../../../docs/techniques/options-cartel/SOURCES.md?raw";
import versions from "../../../docs/techniques/options-cartel/SOURCE-REVIEW.md?raw";
import video from "../../../docs/techniques/options-cartel/VIDEO-REVIEW.md?raw";
import examples from "../../../docs/techniques/options-cartel/EXAMPLES.md?raw";
import ledger from "../../../docs/techniques/options-cartel/LEDGER-REVIEW.md?raw";
import industry from "../../../docs/techniques/options-cartel/INDUSTRY-DATA.md?raw";
import replay from "../../../docs/techniques/options-cartel/REPLAY.md?raw";
import scanning from "../../../docs/techniques/options-cartel/SCANNING.md?raw";

const documents = [
  {file:"METHOD.md", title:"Detailed method", text:method},
  {file:"TRADING-RULES.md", title:"Rules and implementation choices", text:rules},
  {file:"SOURCE-REVIEW.md", title:"Source-version differences", text:versions},
  {file:"VIDEO-REVIEW.md", title:"September video review", text:video},
  {file:"EXAMPLES.md", title:"Trade examples", text:examples},
  {file:"LEDGER-REVIEW.md", title:"Public ledger review", text:ledger},
  {file:"INDUSTRY-DATA.md", title:"Industry evidence", text:industry},
  {file:"REPLAY.md", title:"Replay and comparisons", text:replay},
  {file:"SCANNING.md", title:"Scans and schedules", text:scanning},
  {file:"SOURCES.md", title:"Source coverage", text:sources},
];

export function CartelMethodLibrary() {
  const [file, setFile] = useState("METHOD.md");
  const current = documents.find(d => d.file === file)!;
  const renderLink = useCallback((label: string, href: string) => {
    const local = documents.find(d => d.file === href.split("#")[0]);
    if (local) return <button type="button" onClick={() => setFile(local.file)}>{label}</button>;
    if (/^https?:\/\//i.test(href)) return <a href={href} target="_blank" rel="noreferrer">{label}</a>;
    return <span>{label}</span>;
  }, []);
  return <section className="cartel-library" aria-label="Cartel method library">
    <h2>Method library</h2>
    <p>Source-backed research, historical differences and explicit implementation choices. Reported trade results are not independently verified.</p>
    <label>Read a chapter<select value={file} onChange={e => setFile(e.target.value)}>
      {documents.map(d => <option key={d.file} value={d.file}>{d.title}</option>)}
    </select></label>
    <article aria-label={current.title}><Markdown text={current.text} renderLink={renderLink}/></article>
  </section>;
}
