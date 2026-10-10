"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE_URL } from "@/lib/api-client";

/* ------------------------------------------------------------------ */
/*  ALA — Otak Hukum.                                                  */
/*  Satu halaman: visualisasi otak yang tumbuh seiring ALCD memperoleh */
/*  pemahaman hukum (UU → neuron, pasal/chunk → sinaps, skor → cahaya) */
/* ------------------------------------------------------------------ */

interface AlcdStatus {
  knowledge_ready: boolean;
  knowledge_score: number;
  ontology_nodes: number;
  laws_ingested: number;
  total_chunks: number;
  unresolved_gaps: number;
}
interface NodeLaw {
  law_name: string;
  law_number: string | null;
  law_year: number | string | null;
  chunk_count: number;
  article_count: number;
}
interface OntologyNode {
  subcategory: string | null;
  category: string;
  knowledge_score: number;
  status: string;
  laws?: NodeLaw[];
  articles?: string[]; // pasal nyata di ChromaDB — "isi otak" wilayah ini
}
interface XrefLink {
  fr: number; // index wilayah ontologi sumber (resolved backend)
  fa: string; // pasal sumber
  tr: number; // index wilayah ontologi target
  ta: string; // pasal target
  rel: string; // jenis relasi Neo4j (CROSS_REFERENCES, dst.)
}
interface FeedDoc {
  name: string;
  articles: number;
  chunks: number;
  cat: string;
  ts: string | null;
}
interface QueueItem {
  topic: string;
  status: string;
  score: number;
}
interface AlcdProgress {
  running: boolean;
  stage: string | null;
  topic: string | null;
  detail: string;
  done?: number | null;
  total?: number | null;
  elapsed_s?: number;
  eta_s?: number | null;
  recent?: FeedDoc[];
  queue?: QueueItem[];
}

/* PRNG deterministik — titik neuron stabil antar frame & reload */
function mulberry32(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const MAX_NEURONS = 520;
const MAX_REGIONS = 10;

interface Neuron {
  x: number;
  y: number;
  region: number;
  order: number; // urutan aktivasi — tumbuh menjalar dari inti
  edges: number[];
}

/* Bentuk otak: 2 belahan + serebelum + batang (koordinat 0..1) */
function insideBrain(x: number, y: number): boolean {
  const ell = (cx: number, cy: number, rx: number, ry: number) =>
    ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1;
  return (
    ell(0.38, 0.42, 0.27, 0.33) || // belahan kiri
    ell(0.62, 0.42, 0.27, 0.33) || // belahan kanan
    ell(0.6, 0.74, 0.22, 0.16) || // serebelum
    ell(0.47, 0.78, 0.09, 0.13) // batang otak
  );
}

function buildNeurons(): Neuron[] {
  const rng = mulberry32(1337);
  const pts: { x: number; y: number }[] = [];
  let guard = 0;
  while (pts.length < MAX_NEURONS && guard++ < 20000) {
    const x = rng() * 0.82 + 0.09;
    const y = rng() * 0.84 + 0.08;
    if (insideBrain(x, y)) pts.push({ x, y });
  }
  // Urutan aktivasi: jarak dari "inti" (0.5,0.55) — pertumbuhan menjalar.
  // Wilayah = lobus: sektor sudut dari inti → tiap wilayah punya posisi
  // dan centroid berbeda (label ontologi tidak bertumpuk).
  const neurons: Neuron[] = pts.map((p) => {
    const ang = Math.atan2(p.y - 0.55, p.x - 0.5);
    const region =
      Math.floor(((ang + Math.PI) / (2 * Math.PI)) * MAX_REGIONS +
        rng() * 0.5) % MAX_REGIONS;
    return {
      x: p.x,
      y: p.y,
      region,
      order: Math.hypot(p.x - 0.5, p.y - 0.55) + rng() * 0.08,
      edges: [],
    };
  });
  neurons.sort((a, b) => a.order - b.order);
  // 3 tetangga terdekat sebagai sinaps — SIMETRIS: bila i menunjuk j,
  // j juga menunjuk i. Tanpa ini neuron bisa terisolasi visual: edge
  // hanya digambar indeks-rendah→tinggi, jadi neuron yang seluruh
  // tetangganya berindeks lebih kecil dan tak ditunjuk balik tampil
  // sebagai titik terputus.
  for (let i = 0; i < neurons.length; i++) {
    const dist = neurons
      .map((n, j) => ({ j, d: Math.hypot(n.x - neurons[i].x, n.y - neurons[i].y) }))
      .filter((o) => o.j !== i)
      .sort((a, b) => a.d - b.d)
      .slice(0, 3);
    for (const o of dist) {
      if (!neurons[i].edges.includes(o.j)) neurons[i].edges.push(o.j);
      if (!neurons[o.j].edges.includes(i)) neurons[o.j].edges.push(i);
    }
  }
  return neurons;
}

const NEURONS = buildNeurons();
const REGION_HUES = [162, 190, 145, 205, 175, 155, 215, 168, 195, 150];

/* ------------------------------------------------------------------ */
/*  Terminal aktivitas — narasi live apa yang sedang dipikirkan otak   */
/* ------------------------------------------------------------------ */

type LogKind = "ok" | "info" | "warn" | "err" | "dim";
interface LogLine {
  id: number;
  ts: string;
  tag: string;
  text: string;
  kind: LogKind;
}

/* Aktivitas ambient — diputar di antara event nyata agar terminal selalu
   hidup; semuanya tahapan nyata pipeline ALCD. */
const AMBIENT: [string, string][] = [
  ["SCAN", "memindai indeks peraturan.bpk.go.id …"],
  ["SCAN", "crawl domain terpercaya: jdih.* · bpk · mahkamahagung"],
  ["PLAN", "kurikulum: menalar UU relevan untuk node ontologi"],
  ["FETCH", "GET /Download/… · peraturan.bpk.go.id"],
  ["FETCH", "GET /Search?keywords=… · kandidat sumber"],
  ["PARSE", "ekstraksi PDF → teks · deteksi struktur Pasal"],
  ["PARSE", "memotong bagian PENJELASAN — jaga teks normatif"],
  ["VERIFY", "cocokkan NOMOR/TAHUN blok judul ↔ metadata sumber"],
  ["VERIFY", "uji topik: kata khas subjek dalam dokumen"],
  ["REJECT", "kandidat tak cocok identitas — dibuang"],
  ["EMBED", "multilingual-e5 · passage: → vektor 384-d"],
  ["STORE", "upsert chunk → chroma://indonesian_laws"],
  ["GRAPH", "node LegalArticle + CROSS_REFERENCES → neo4j"],
  ["EVAL", "kuis mandiri node ontologi · skor jawaban"],
  ["EVAL", "LLM-as-judge: menilai pemahaman per wilayah"],
];

const KIND_CLS: Record<LogKind, string> = {
  ok: "text-emerald-300",
  info: "text-cyan-300/80",
  warn: "text-amber-300/90",
  err: "text-red-400/80",
  dim: "text-emerald-200/40",
};
const TAG_CLS: Record<LogKind, string> = {
  ok: "text-emerald-400",
  info: "text-cyan-400/70",
  warn: "text-amber-400/80",
  err: "text-red-400/90",
  dim: "text-emerald-300/30",
};

const randHex = (n: number) =>
  Array.from({ length: n }, () =>
    "0123456789abcdef"[Math.floor(Math.random() * 16)]
  ).join("");

/* Decode aman — detail backend dipotong slice() dan bisa memutus
   sekuensi %XX; decodeURIComponent melempar URIError pada input itu */
const safeDecode = (s: string): string => {
  try {
    return decodeURIComponent(s);
  } catch {
    return s.replace(/%[0-9A-Fa-f]{2}/g, " ");
  }
};

/* Tahapan proses otak — dipetakan dari tag log; panel kiri menampilkan
   apa yang sedang dikerjakan otak (memindai → memahami → menyambungkan) */
const STAGES: [string, string][] = [
  ["PLAN", "merumuskan kurikulum"],
  ["DOKTRIN", "menyerap ilmu hukum dasar"],
  ["IMPORT", "menyerap korpus terverifikasi"],
  ["SCAN", "memindai sumber resmi"],
  ["FETCH", "mengunduh dokumen"],
  ["PARSE", "membaca & memecah pasal"],
  ["VERIFY", "memverifikasi identitas"],
  ["EMBED", "menanam pengetahuan"],
  ["GRAPH", "menyambungkan pasal"],
  ["EVAL", "mengevaluasi diri"],
];
const TAG_STAGE: Record<string, string> = {
  BOOT: "PLAN", ONTO: "PLAN", PLAN: "PLAN",
  DOKTRIN: "DOKTRIN",
  IMPORT: "IMPORT",
  SCAN: "SCAN",
  FETCH: "FETCH",
  PARSE: "PARSE",
  VERIFY: "VERIFY", REJECT: "VERIFY",
  EMBED: "EMBED", STORE: "EMBED", SINAPS: "EMBED", INGEST: "EMBED",
  GRAPH: "GRAPH",
  EVAL: "EVAL", GAP: "EVAL", READY: "EVAL",
};

/* Fragmen fallback — dipakai hanya untuk wilayah yang BELUM punya
   dokumen terverifikasi; wilayah berisi menampilkan pasal asli */
const NEURON_TOKENS = [
  "Pasal 362", "ayat (1)", "mens rea", "delik", "KUHP", "Pasal 55",
  "alat bukti", "vide", "dakwaan", "penyidikan", "Pasal 184", "putusan",
  "tersangka", "KUHAP", "Pasal 45A", "gratifikasi", "TPPU", "BAB II",
  "ayat (2)", "melawan hukum", "Pasal 3", "UU 1/2023", "BAB VII", "§19",
];

interface Pulse {
  from: number;
  to: number;
  t: number;
  speed: number;
  label: string; // fragmen pengetahuan yang "mengalir" di sinaps
  target?: number; // neuron tujuan — paket delivery (bukan random walk)
  hops?: number; // batas lompatan agar paket tak mengembara selamanya
  xref?: boolean; // mengalir di jalur rujukan antar-pasal nyata (amber)
}

export default function BrainPage() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const statsRef = useRef<{
    alcd: AlcdStatus | null;
    nodes: OntologyNode[];
    links: XrefLink[];
  }>({ alcd: null, nodes: [], links: [] });
  /* Progres nyata bootstrap — kamera & log mengikuti ini, bukan acak */
  const progRef = useRef<AlcdProgress>({
    running: false,
    stage: null,
    topic: null,
    detail: "",
  });
  const lastProgKey = useRef("");
  /* Tahap yang benar-benar teramati dari _PROGRESS backend sesi ini —
     ambient TIDAK boleh menandai tahap (itu narasi, bukan fakta). */
  const seenStages = useRef<Set<string>>(new Set());
  const [alcd, setAlcd] = useState<AlcdStatus | null>(null);
  const [nodes, setNodes] = useState<OntologyNode[]>([]);
  const [tick, setTick] = useState(0); // force HUD re-render saat chunks bertambah
  const [lines, setLines] = useState<LogLine[]>([]);
  const logId = useRef(0);
  const ambientIdx = useRef(-1);
  const [typed, setTyped] = useState(0); // typewriter baris terakhir
  const [stage, setStage] = useState("PLAN"); // proses otak saat ini
  const [feed, setFeed] = useState<{
    recent: FeedDoc[];
    queue: QueueItem[];
    sedang: {
      stage: string; topic: string; detail: string;
      done: number | null; total: number | null;
      elapsed_s: number; eta_s: number | null;
    } | null;
  }>({ recent: [], queue: [], sedang: null });
  const [focusLabel, setFocusLabel] = useState("inti");
  const focusRef = useRef("inti"); // ditulis loop kanvas tiap frame
  const [camReason, setCamReason] = useState("gambaran umum otak");
  const reasonRef = useRef("gambaran umum otak"); // alasan gerak kamera
  const wrapRef = useRef<HTMLDivElement>(null);
  const [isFs, setIsFs] = useState(false);

  const toggleFullscreen = () => {
    const el = wrapRef.current;
    if (!el) return;
    if (document.fullscreenElement) document.exitFullscreen();
    else el.requestFullscreen().catch(() => {});
  };

  useEffect(() => {
    const onFs = () => setIsFs(!!document.fullscreenElement);
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "f" && !e.metaKey && !e.ctrlKey)
        toggleFullscreen();
    };
    document.addEventListener("fullscreenchange", onFs);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("fullscreenchange", onFs);
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  const pushLog = (tag: string, text: string, kind: LogKind = "info") => {
    const line: LogLine = {
      id: ++logId.current,
      ts: new Date().toLocaleTimeString("id-ID", { hour12: false }),
      tag,
      text,
      kind,
    };
    setLines((ls) => [...ls.slice(-40), line]);
    setTyped(0);
    const st = TAG_STAGE[tag];
    if (st) setStage(st);
  };

  /* Typewriter — baris terbaru muncul per karakter */
  const lastText = lines.length ? lines[lines.length - 1].text : "";
  useEffect(() => {
    if (typed >= lastText.length) return;
    const id = setTimeout(() => setTyped((t) => t + 2), 18);
    return () => clearTimeout(id);
  }, [typed, lastText]);

  /* Poll metrik pengetahuan — endpoint GLOBAL tanpa auth */
  useEffect(() => {
    let alive = true;
    const pull = async () => {
      try {
        const [s, o] = await Promise.all([
          fetch(`${API_BASE_URL}/api/v1/alcd/status`).then((r) => r.json()),
          fetch(`${API_BASE_URL}/api/v1/alcd/ontology`).then((r) => r.json()),
        ]);
        if (!alive) return;
        const prev = statsRef.current.alcd;
        const prevNodes = statsRef.current.nodes;
        /* Pengetahuan yatim: UU teregistrasi yang belum tertampung node
           ontologi — ditampilkan jujur sebagai wilayah KORPUS LUAS */
        const rawNodes: OntologyNode[] = o.nodes ?? [];
        const orphans: string[] = o.unassigned_laws ?? [];
        const allNodes = orphans.length
          ? [...rawNodes, {
              subcategory: "Korpus Luas",
              category: "Korpus Luas",
              knowledge_score: 0.5,
              status: "in_progress",
              laws: orphans.map((nm) => ({
                law_name: nm,
                law_number: null,
                law_year: null,
                chunk_count: 0,
                article_count: 0,
              })),
            }]
          : rawNodes;
        statsRef.current = {
          alcd: s,
          nodes: allNodes,
          links: o.links ?? [],
        };
        setAlcd(s);
        setNodes(allNodes);
        if ((s?.total_chunks ?? 0) !== (prev?.total_chunks ?? -1))
          setTick((t) => t + 1);

        /* Event nyata dari diff metrik → baris terminal */
        if (prev && s) {
          if (s.laws_ingested > prev.laws_ingested) {
            const known = new Set(
              prevNodes.flatMap((n) =>
                (n.laws ?? []).map((l) => l.law_name)));
            const fresh = (o.nodes ?? []).flatMap(
              (n: OntologyNode) => n.laws ?? []
            ).find((l: NodeLaw) => !known.has(l.law_name));
            pushLog(
              "INGEST",
              `${fresh ? fresh.law_name.slice(0, 46) : "UU terverifikasi"} ditanam — total ${s.laws_ingested} dokumen`,
              "ok"
            );
          }
          const dc = s.total_chunks - prev.total_chunks;
          if (dc > 0)
            pushLog("SINAPS", `+${dc} pasal tertanam → chroma://indonesian_laws`, "info");
          if (s.ontology_nodes > prev.ontology_nodes)
            pushLog("ONTO", `wilayah ontologi bertambah → ${s.ontology_nodes} node`, "info");
          if (s.unresolved_gaps > prev.unresolved_gaps)
            pushLog("GAP", "celah pengetahuan terdeteksi — riset ulang dijadwalkan", "warn");
          if (!prev.knowledge_ready && s.knowledge_ready)
            pushLog("READY", `ambang kesiapan tercapai — pemahaman ${Math.round(s.knowledge_score * 100)}%`, "ok");
        }
      } catch {
        /* API belum siap — coba lagi di siklus berikut */
      }
    };
    pull();
    const id = setInterval(pull, 5000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  /* Progres kerja nyata ALCD — sumber kebenaran untuk kamera, panel
     PROSES OTAK, dan neural.log. Dedup via (stage|topic|detail). */
  useEffect(() => {
    const PROG_TAG: Record<string, string> = {
      ontology: "PLAN", acquire: "SCAN", plan: "PLAN", fetch: "FETCH",
      parse: "PARSE", reject: "REJECT", ingest: "INGEST", graph: "GRAPH",
      self_eval: "EVAL", done: "READY", doktrin: "DOKTRIN",
      import: "IMPORT",
    };
    const pull = async () => {
      try {
        const p: AlcdProgress = await fetch(
          `${API_BASE_URL}/api/v1/alcd/progress`
        ).then((r) => r.json());
        progRef.current = p;
        setFeed({
          recent: p.recent ?? [],
          queue: p.queue ?? [],
          sedang: p.running && p.topic
            ? {
                stage: p.stage ?? "",
                topic: p.topic,
                detail: p.detail ?? "",
                done: p.done ?? null,
                total: p.total ?? null,
                elapsed_s: p.elapsed_s ?? 0,
                eta_s: p.eta_s ?? null,
              }
            : null,
        });
        const key = `${p.stage}|${p.topic}|${p.detail}`;
        if (p.stage && key !== lastProgKey.current) {
          lastProgKey.current = key;
          const tag = PROG_TAG[p.stage] ?? p.stage.toUpperCase().slice(0, 7);
          const kind: LogKind =
            tag === "REJECT" ? "err"
            : tag === "INGEST" || tag === "READY" ? "ok"
            : "info";
          const stKey = TAG_STAGE[tag];
          if (stKey) seenStages.current.add(stKey);
          pushLog(
            tag,
            `${p.topic ?? "global"} · ${p.detail || p.stage}`.slice(0, 78),
            kind
          );
        }
      } catch {
        /* API belum siap */
      }
    };
    pull();
    const id = setInterval(pull, 2000);
    return () => clearInterval(id);
  }, []);

  /* Baris ambient — narasi aktivitas di antara event nyata. DIREDAM
     selama bootstrap berjalan: kerja nyata yang menarasikan dirinya. */
  const booted = useRef(false);
  useEffect(() => {
    if (!booted.current) {
      booted.current = true;
      pushLog("BOOT", "ALA neural core · inisialisasi dari NOL data", "ok");
    }
    const id = setInterval(() => {
      setFocusLabel(focusRef.current);
      setCamReason(reasonRef.current);
      if (progRef.current.running) return; // biarkan event nyata bicara
      let i = Math.floor(Math.random() * AMBIENT.length);
      if (i === ambientIdx.current) i = (i + 1) % AMBIENT.length;
      ambientIdx.current = i;
      const [tag, text] = AMBIENT[i];
      const suffix = tag === "STORE" || tag === "EMBED"
        ? ` · 0x${randHex(8)}`
        : "";
      const kind: LogKind =
        tag === "REJECT" ? "err" : tag === "EVAL" ? "warn" : "dim";
      pushLog(tag, text + suffix, kind);
    }, 2600);
    return () => clearInterval(id);
  }, []);

  /* Loop render kanvas */
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let raf = 0;
    const pulses: Pulse[] = [];
    let pulseArtCursor = 0; // pasal berikutnya yang "dikirim" ke wilayah fokus
    const flashes = new Map<number, number>(); // neuron → waktu paket terkirim

    /* Kamera — zoom in ke wilayah yang sedang belajar, out saat idle.
       Selang-seling: survey wilayah (~1.5×) ↔ menyelam ke neuron (~3×) */
    const cam = { z: 1, cx: 0.5, cy: 0.5 };
    let focusRegion = -1;
    let focusNeuron = -1;
    let deepDive = false;
    let focusSwitch = -20000; // mulai di tengah jeda — patroli pertama cepat
    let patrolIdx = -1;
    let prevChunks = 0;
    let activity = 0;
    /* prefers-reduced-motion: kamera tetap utuh, tanpa menyelam */
    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = window.innerWidth * dpr;
      canvas.height = window.innerHeight * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);

    const draw = (time: number) => {
      const w = window.innerWidth;
      const h = window.innerHeight;
      const { alcd: s, nodes } = statsRef.current;
      const chunks = s?.total_chunks ?? 0;
      const laws = s?.laws_ingested ?? 0;
      const score = s?.knowledge_score ?? 0;

      /* Otak kosong = NOL data: hanya segelintir neuron redup.
         Pertumbuhan: ~1 neuron per 6 sinaps + 6 per UU. */
      const active = Math.min(
        MAX_NEURONS,
        12 + Math.floor(chunks / 6) + laws * 6
      );
      const brightness = 0.25 + score * 0.75;

      /* — Kamera: saat bootstrap berjalan, fokus MENGIKUTI wilayah yang
           sedang dikerjakan (progress nyata /alcd/progress) — bukan acak.
           Saat idle: survey wilayah tiap ~6 dtk, selang-seling menyelam. — */
      const prog = progRef.current;
      const grown = Math.max(0, chunks - prevChunks);
      prevChunks = chunks;
      const busy = grown > 0 ? 1 : s && !s.knowledge_ready ? 0.55 : 0.15;
      activity += (busy - activity) * 0.02;
      /* Patroli idle — bukan zoom acak. Tiap ~14 dtk kamera meninjau
         SEKILAS (~5 dtk, 1.35×) wilayah terkaya berikutnya secara
         bergiliran, lalu kembali ke gambaran umum. Menyelam dalam
         hanya untuk kerja nyata (prog.running di bawah). Alasan
         selalu tertulis di HUD agar gerakan tidak tampak sembarang. */
      const dwellMs = 5000;
      if (!prog.running) {
        deepDive = false;
        focusNeuron = -1;
        if (time - focusSwitch > 14000) {
          focusSwitch = time;
          const scored = nodes
            .map((n, i) => ({ i, s: n?.knowledge_score ?? 0 }))
            .filter((o) => o.i < MAX_REGIONS)
            .sort((a, b) => b.s - a.s);
          if (scored.length) {
            patrolIdx = (patrolIdx + 1) % scored.length;
            focusRegion = scored[patrolIdx].i;
            focusRef.current =
              nodes[focusRegion]?.subcategory ??
              `wilayah ${focusRegion + 1}`;
          }
        }
      }
      reasonRef.current = prog.running
        ? `mengikuti kerja: ${prog.stage ?? ""} · ${prog.topic ?? ""}`
        : time - focusSwitch < dwellMs
          ? "patroli wilayah berkala"
          : "gambaran umum otak";
      if (prog.running && prog.topic) {
        const tq = (prog.topic || "").toUpperCase();
        /* Resolver wilayah: exact → containment dua arah → alias semantik
           (korpus eksternal → KORPUS LUAS; doktrin → node ILMU HUKUM) */
        let ti = nodes.findIndex(
          (n) => (n.subcategory || n.category || "").toUpperCase() === tq
        );
        if (ti < 0)
          ti = nodes.findIndex((n) => {
            const nm = (n.subcategory || n.category || "").toUpperCase();
            return nm && (nm.includes(tq) || tq.includes(nm));
          });
        if (ti < 0 && /KORPUS|SPKT|LEXIS|EKSTERNAL/.test(tq))
          ti = nodes.findIndex((n) =>
            (n.subcategory || "").toUpperCase().includes("KORPUS LUAS")
          );
        if (ti < 0 && /ILMU|DOKTRIN|ASAS|HUKUM/.test(tq))
          ti = nodes.findIndex((n) =>
            /DOKTRIN|ASAS|ILMU/.test(
              (n.subcategory || n.category || "").toUpperCase()
            )
          );
        if (ti >= 0) {
          /* Node di luar wilayah fisik otak (>= MAX_REGIONS, mis. Korpus
             Luas) tak punya neuron — fokus SELURUH otak, bukan crash */
          const physTi = ti < MAX_REGIONS ? ti : -1;
          focusRegion = physTi;
          focusRef.current = prog.topic;
          /* Menyelam saat kerja detail, survey saat scan/plan/eval —
             zoom sesuai tahap yang tampil di panel */
          deepDive = physTi >= 0 &&
            ["parse", "ingest", "graph", "import", "fetch"].includes(
              prog.stage ?? ""
            );
          if (deepDive) {
            if (focusNeuron < 0 || NEURONS[focusNeuron].region !== physTi) {
              const pool: number[] = [];
              for (let i = 0; i < active; i++)
                if (NEURONS[i].region === physTi) pool.push(i);
              focusNeuron = pool.length
                ? pool[Math.floor(Math.random() * pool.length)]
                : -1;
            }
          } else {
            focusNeuron = -1;
          }
        }
      }
      let tx = 0.5, ty = 0.5, cnt = 0;
      if (focusNeuron >= 0) {
        tx = NEURONS[focusNeuron].x;
        ty = NEURONS[focusNeuron].y;
      } else {
        for (let i = 0; i < active; i++) {
          if (NEURONS[i].region === focusRegion) {
            tx += NEURONS[i].x; ty += NEURONS[i].y; cnt++;
          }
        }
        if (cnt) { tx /= cnt; ty /= cnt; }
      }
      tx = Math.min(Math.max(tx, 0.18), 0.82);
      ty = Math.min(Math.max(ty, 0.18), 0.82);
      const zT = reduceMotion
        ? 1
        : prog.running
          ? 1 +
            activity * (deepDive ? 2.1 : 0.8) *
              (s?.knowledge_ready ? 0.55 : 1)
          : time - focusSwitch < dwellMs && focusRegion >= 0
            ? 1.35 // patroli sekilas — cukup untuk membaca label wilayah
            : 1;
      cam.z += (zT - cam.z) * 0.015;
      cam.cx += (tx - cam.cx) * 0.015;
      cam.cy += (ty - cam.cy) * 0.015;

      ctx.fillStyle = "#020204";
      ctx.fillRect(0, 0, w, h);

      const px = (n: Neuron) => w * 0.5 + (n.x - cam.cx) * cam.z * w;
      const py = (n: Neuron) => h * 0.5 + (n.y - cam.cy) * cam.z * h;

      /* Titik kontrol bezier — sinaps melengkung organik (bukan garis
         lurus); flip bergantian agar kurva tidak searah */
      const curveCP = (a: Neuron, b: Neuron) => {
        const ax = px(a), ay = py(a), bx = px(b), by = py(b);
        const mx = (ax + bx) / 2, my = (ay + by) / 2;
        const dx = bx - ax, dy = by - ay;
        const d = Math.hypot(dx, dy) || 1;
        const off = d * 0.12 * (((a.x * 97 + b.x * 131) | 0) % 2 ? 1 : -1);
        return { x: mx + (-dy / d) * off, y: my + (dx / d) * off };
      };

      /* Siluet otak penuh — neuron dorman tampak redup sehingga bentuk
         otak selalu menguasai layar sejak NOL data */
      for (let i = active; i < MAX_NEURONS; i++) {
        const n = NEURONS[i];
        ctx.fillStyle = `hsla(${REGION_HUES[n.region]},58%,50%,0.10)`;
        ctx.beginPath();
        ctx.arc(px(n), py(n), 1.3, 0, Math.PI * 2);
        ctx.fill();
      }

      /* Sinaps — dua lapis: glow lebar redup + inti tipis terang */
      for (let i = 0; i < active; i++) {
        const n = NEURONS[i];
        const hue = REGION_HUES[n.region];
        const regionScore = nodes[n.region]?.knowledge_score ?? 0;
        const alpha =
          0.05 + 0.14 * brightness + 0.1 * Math.min(1, regionScore);
        for (const j of n.edges) {
          if (j >= active || j <= i) continue;
          const m = NEURONS[j];
          const cp = curveCP(n, m);
          ctx.beginPath();
          ctx.moveTo(px(n), py(n));
          ctx.quadraticCurveTo(cp.x, cp.y, px(m), py(m));
          ctx.strokeStyle = `hsla(${hue},75%,55%,${alpha * 0.35})`;
          ctx.lineWidth = 2.4;
          ctx.stroke();
          ctx.strokeStyle = `hsla(${hue},70%,60%,${alpha})`;
          ctx.lineWidth = 0.6;
          ctx.stroke();
        }
      }

      /* Sinaps bermakna — relasi rujukan antar-pasal nyata (Neo4j
         CROSS_REFERENCES). Neuron wilayah dipetakan ke pasal nyata;
         edge amber putus-putus = "pasal ini mengutip pasal itu". */
      const regionNeurons: number[][] = Array.from(
        { length: MAX_REGIONS }, () => []);
      for (let i = 0; i < active; i++)
        regionNeurons[NEURONS[i].region].push(i);
      const artNeuron = new Map<string, number>();
      for (let r = 0; r < Math.min(nodes.length, MAX_REGIONS); r++) {
        const arts = nodes[r]?.articles ?? [];
        const ns = regionNeurons[r];
        arts.forEach((a2, k) => {
          const key = `${r}|${a2}`;
          if (!artNeuron.has(key) && ns.length)
            artNeuron.set(key, ns[k % ns.length]);
        });
      }
      const xrefPairs: { ia: number; ib: number; fa: string; ta: string }[] = [];
      const links = statsRef.current.links;
      if (links.length && active > 0) {
        ctx.setLineDash([5, 4]);
        let drawn = 0;
        for (const l of links) {
          if (drawn >= 60) break;
          const ia = artNeuron.get(`${l.fr}|${l.fa}`);
          const ib = artNeuron.get(`${l.tr}|${l.ta}`);
          if (ia == null || ib == null || ia === ib ||
              ia >= active || ib >= active) continue;
          xrefPairs.push({ ia, ib, fa: l.fa, ta: l.ta });
          const a = NEURONS[ia], b = NEURONS[ib];
          const cp = curveCP(a, b);
          ctx.strokeStyle = `hsla(45,90%,62%,${0.12 + 0.25 * brightness})`;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(px(a), py(a));
          ctx.quadraticCurveTo(cp.x, cp.y, px(b), py(b));
          ctx.stroke();
          drawn++;
          /* Alasan tersambung — tampak saat menyelam */
          if (cam.z > 1.9) {
            ctx.font = "7px ui-monospace, monospace";
            ctx.textAlign = "center";
            ctx.fillStyle = "hsla(45,90%,70%,0.75)";
            ctx.fillText(`${l.fa} → ${l.ta}`, cp.x, cp.y - 3);
          }
        }
        ctx.setLineDash([]);
      }

      /* Neuron — menyala sebentar saat paket pengetahuan terkirim ke sana */
      for (let i = 0; i < active; i++) {
        const n = NEURONS[i];
        const hue = REGION_HUES[n.region];
        const fl = flashes.get(i);
        const boost = fl ? Math.max(0, 1 - (time - fl) / 600) : 0;
        const glow =
          0.35 + 0.4 * brightness + 0.25 * Math.sin(time / 900 + i) +
          0.6 * boost;
        ctx.fillStyle = `hsla(${hue},75%,62%,${Math.max(0.12, glow)})`;
        ctx.beginPath();
        ctx.arc(px(n), py(n), i % 17 === 0 ? 2.2 : 1.4, 0, Math.PI * 2);
        ctx.fill();
      }

      /* Label wilayah ontologi di centroid tiap region aktif */
      const cent: Record<number, { x: number; y: number; c: number }> = {};
      for (let i = 0; i < active; i++) {
        const n = NEURONS[i];
        const c = cent[n.region] ?? (cent[n.region] = { x: 0, y: 0, c: 0 });
        c.x += n.x; c.y += n.y; c.c++;
      }
      ctx.textAlign = "center";
      ctx.font = "600 10px ui-monospace, monospace";
      // Label wilayah memudar saat menyelam (hindari tumpang tindih)
      const regionAlpha =
        (0.28 + 0.3 * brightness) * Math.min(1, Math.max(0, 1.9 - cam.z));
      for (const [r, c] of Object.entries(cent)) {
        const node = nodes[+r];
        const label = node?.subcategory ?? `REGION ${+r + 1}`;
        const lx = w * 0.5 + (c.x / c.c - cam.cx) * cam.z * w;
        const ly = h * 0.5 + (c.y / c.c - cam.cy) * cam.z * h;
        ctx.fillStyle = `hsla(${REGION_HUES[+r]},85%,72%,${regionAlpha})`;
        ctx.fillText(label.toUpperCase(), lx, ly - 10);
        /* Baris kedua: UU NYATA yang tertanam di wilayah ini */
        const lawTags = (node?.laws ?? [])
          .map((l) =>
            l.law_number
              ? `UU ${l.law_number}/${l.law_year}`
              : l.law_name.slice(0, 20)
          )
          .slice(0, 3)
          .join(" · ");
        const sub = node
          ? lawTags || "∅ belum ada dokumen"
          : "belum dirumuskan";
        ctx.font = "7px ui-monospace, monospace";
        ctx.fillStyle = `hsla(${REGION_HUES[+r]},80%,68%,${
          regionAlpha * 0.8})`;
        ctx.fillText(sub, lx, ly + 1);
        ctx.font = "600 10px ui-monospace, monospace";
      }

      /* Label mikro per neuron — PASAL ASLI yang tertanam di wilayah
         ini (dari metadata Chroma); wilayah kosong pakai fragmen
         generik sebagai placeholder pengetahuan yang dituju */
      const artOf = (region: number, i: number): string => {
        const arts = nodes[region]?.articles;
        if (arts && arts.length) return arts[i % arts.length];
        return NEURON_TOKENS[i % NEURON_TOKENS.length];
      };
      if (cam.z > 1.18) {
        const la = Math.min(0.85, (cam.z - 1.18) * 1.8);
        const step = cam.z > 2.2 ? 5 : 9;
        ctx.textAlign = "left";
        ctx.font = "7px ui-monospace, monospace";
        for (let i = 0; i < active; i += step) {
          const n = NEURONS[i];
          ctx.fillStyle = `hsla(${REGION_HUES[n.region]},60%,65%,${la * 0.5})`;
          ctx.fillText(artOf(n.region, i), px(n) + 5, py(n) - 4);
        }
      }

      /* Pulsa sinyal = PAKET DATA NYATA yang sedang diproses:
         - fetch/parse/ingest → paket pasal asli mengalir MASUK ke wilayah
           fokus (routing greedy ke neuron tujuan), padam saat terkirim
         - graph → paket amber mengalir di jalur rujukan antar-pasal nyata
         - idle → random walk ambient yang jarang (otak diam) */
      const focusArts =
        focusRegion >= 0 ? nodes[focusRegion]?.articles ?? [] : [];
      const focusPool = focusRegion >= 0 ? regionNeurons[focusRegion] : [];
      const bestHop = (i: number, target: number): number | null => {
        const T = NEURONS[target];
        let best: number | null = null, bd = Infinity;
        for (const j of NEURONS[i].edges) {
          if (j >= active) continue;
          const d = Math.hypot(NEURONS[j].x - T.x, NEURONS[j].y - T.y);
          if (d < bd) { bd = d; best = j; }
        }
        return best;
      };
      const targetPulses = Math.min(
        4 + Math.floor(chunks / 60) + (prog.running ? 14 : 0) +
          (s?.knowledge_ready ? 6 : 0),
        46
      );
      while (pulses.length < targetPulses && active > 2) {
        /* Paket rujukan — tahap GRAPH: mengalir di edge amber nyata */
        if (prog.running && prog.stage === "graph" && xrefPairs.length &&
            Math.random() < 0.55) {
          const lp = xrefPairs[Math.floor(Math.random() * xrefPairs.length)];
          pulses.push({
            from: lp.ia, to: lp.ib, t: 0,
            speed: 0.01 + Math.random() * 0.015,
            label: `${lp.fa} → ${lp.ta}`, xref: true,
          });
          continue;
        }
        /* Paket delivery — menuju wilayah yang sedang diproses */
        if (prog.running && focusPool.length && Math.random() < 0.7) {
          const target =
            focusPool[Math.floor(Math.random() * focusPool.length)];
          const from = Math.floor(Math.random() * active);
          if (from === target) continue;
          const to = bestHop(from, target);
          if (to == null) continue;
          pulses.push({
            from, to, t: 0,
            speed: 0.012 + Math.random() * 0.02,
            label: focusArts.length
              ? focusArts[pulseArtCursor++ % focusArts.length]
              : safeDecode(prog.detail || prog.topic || "data")
                  .replace(/\.pdf$/i, "")
                  .replace(/[-_]/g, " ")
                  .replace(/%[0-9A-Fa-f]{0,1}$/, "")
                  .slice(0, 26),
            target,
          });
          continue;
        }
        /* Ambient — random walk saat idle */
        const from = Math.floor(Math.random() * active);
        const to = NEURONS[from].edges[
          Math.floor(Math.random() * NEURONS[from].edges.length)
        ];
        if (to < active) {
          const arts = nodes[NEURONS[from].region]?.articles;
          pulses.push({
            from, to, t: 0,
            speed: 0.008 + Math.random() * 0.02,
            label: arts?.length
              ? arts[Math.floor(Math.random() * arts.length)]
              : NEURON_TOKENS[
                  Math.floor(Math.random() * NEURON_TOKENS.length)
                ],
          });
        }
      }
      for (let i = pulses.length - 1; i >= 0; i--) {
        const p = pulses[i];
        p.t += p.speed;
        if (p.t >= 1) {
          if (p.xref) { pulses.splice(i, 1); continue; }
          if (p.target != null && p.to === p.target) {
            /* Paket TERKIRIM — neuron tujuan menyala, paket padam */
            flashes.set(p.target, time);
            pulses.splice(i, 1);
            continue;
          }
          p.hops = (p.hops ?? 0) + 1;
          if (p.hops > 26) { pulses.splice(i, 1); continue; }
          const next = p.target != null
            ? bestHop(p.to, p.target)
            : NEURONS[p.to].edges[
                Math.floor(Math.random() * NEURONS[p.to].edges.length)
              ];
          if (next != null && next < active) {
            p.from = p.to;
            p.to = next;
            p.t = 0;
          } else {
            pulses.splice(i, 1);
            continue;
          }
        }
        const a = NEURONS[p.from];
        const b = NEURONS[p.to];
        // Posisi pada kurva bezier yang sama dengan sinaps
        const cp = curveCP(a, b);
        const t = p.t, u = 1 - t;
        const x = u * u * px(a) + 2 * u * t * cp.x + t * t * px(b);
        const y = u * u * py(a) + 2 * u * t * cp.y + t * t * py(b);
        const hue = p.xref ? 45 : REGION_HUES[a.region];
        // Jejak ekor — paket delivery/xref selalu berjejak agar
        // arah aliran data terlihat tanpa harus menyelam
        if (cam.z > 1.9 || p.target != null || p.xref) {
          ctx.strokeStyle = `hsla(${hue},85%,65%,${0.4 * t})`;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(px(a), py(a));
          ctx.quadraticCurveTo(cp.x, cp.y, x, y);
          ctx.stroke();
        }
        // Halo radial — sinyal "bercahaya" ala visualisasi synapse modern
        const glowR = cam.z > 1.9 ? 11 : 7;
        const g = ctx.createRadialGradient(x, y, 0, x, y, glowR);
        g.addColorStop(0, `hsla(${hue},95%,70%,0.5)`);
        g.addColorStop(1, `hsla(${hue},95%,70%,0)`);
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(x, y, glowR, 0, Math.PI * 2);
        ctx.fill();
        // Inti sinyal
        ctx.fillStyle = `hsla(${hue},95%,80%,0.95)`;
        ctx.beginPath();
        ctx.arc(x, y, cam.z > 1.9 ? 2.6 : 2, 0, Math.PI * 2);
        ctx.fill();
        /* Label paket: paket delivery & rujukan SELALU terlihat (itulah
           informasinya); ambient hanya saat menyelam dalam */
        const showLabel =
          cam.z > 1.9 || ((p.target != null || p.xref) && cam.z > 1.3);
        if (showLabel) {
          ctx.font = "7px ui-monospace, monospace";
          ctx.textAlign = "left";
          ctx.fillStyle = `hsla(${hue},85%,78%,0.85)`;
          ctx.fillText(p.label, x + 6, y - 4);
        }
      }

      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
  }, [tick]);

  const score = Math.round((alcd?.knowledge_score ?? 0) * 100);
  const learning = !alcd?.knowledge_ready;

  return (
    <div
      ref={wrapRef}
      className="scanlines crt-vignette dot-grid relative h-screen w-screen overflow-hidden bg-black"
    >
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />

      {/* Judul */}
      <div className="absolute left-6 top-6 select-none">
        <h1 className="text-glow font-term text-lg font-semibold tracking-[0.3em] text-emerald-300/95">
          ALA
        </h1>
        <p className="font-term mt-1 text-[11px] tracking-widest text-emerald-200/40">
          AUTONOMOUS LEGAL AGENT — OTAK HUKUM
        </p>
      </div>

      {/* Panel proses otak — pipeline nyata: ✓ sudah diamati, ● aktif
          (dengan detail live), ◌ belum pernah. Saat idle runtuh jadi
          satu baris siaga — bukan legenda statis. */}
      <div className="font-term absolute bottom-[150px] left-6 top-28 flex w-[330px] select-none flex-col overflow-hidden text-[11px] leading-6">
        <div className="mb-1 shrink-0 tracking-widest text-emerald-300/45">
          PROSES OTAK
        </div>
        {(() => {
          const seen = seenStages.current;
          const running = progRef.current.running;
          if (!running) {
            const last = Array.from(seen).pop();
            const lastLabel = STAGES.find(([k]) => k === last)?.[1];
            return (
              <div className="text-emerald-200/30">
                ⊙ siaga
                {lastLabel && (
                  <span className="text-emerald-200/20">
                    {" "}— siklus terakhir: {lastLabel}
                  </span>
                )}
              </div>
            );
          }
          const activeIdx = STAGES.findIndex(([k]) => k === stage);
          return STAGES.map(([key, label], i) => {
            const on = stage === key;
            /* Pipeline sekuensial: tahap di atas aktif sudah dilewati */
            const done = (seen.has(key) || i < activeIdx) && !on;
            return (
              <div
                key={key}
                className={`flex items-center gap-2 ${
                  on
                    ? "text-glow-dim text-emerald-300"
                    : done
                      ? "text-emerald-200/30"
                      : "text-emerald-200/10"
                }`}
              >
                <span className={on ? "animate-pulse" : ""}>
                  {on ? "●" : done ? "✓" : "◌"}
                </span>
                <span className={on ? "tracking-wider" : ""}>{label}</span>
                {on && feed.sedang?.detail && (
                  <span className="max-w-[200px] truncate text-[10px] text-amber-200/50">
                    · {safeDecode(feed.sedang.detail)}
                  </span>
                )}
              </div>
            );
          });
        })()}
        <div className="mt-3 text-[10px] text-emerald-200/30">
          fokus wilayah{" "}
          <span className="text-glow-dim text-emerald-300/75">
            {focusLabel.toUpperCase()}
          </span>
        </div>
        <div className="text-[9px] text-emerald-200/20">
          kamera: {camReason}
        </div>

        {/* Feed hidup — sedang diproses / baru dimiliki / rencana */}
        {feed.sedang && (() => {
          const sd = feed.sedang;
          const pct = sd.total
            ? Math.min(100, Math.round(((sd.done ?? 0) / sd.total) * 100))
            : null;
          const fmtDur = (s: number) =>
            s >= 3600
              ? `${Math.floor(s / 3600)}j ${Math.floor((s % 3600) / 60)}m`
              : s >= 60
                ? `${Math.floor(s / 60)}m ${s % 60}s`
                : `${s}s`;
          return (
            <div className="mt-4 text-[10px] leading-4">
              <div className="tracking-widest text-amber-300/60">
                ▸ SEDANG DIPROSES
              </div>
              <div className="pl-3 text-amber-200/85">
                <span className="caret-blink">▊</span>{" "}
                {sd.topic}
                {sd.detail && (
                  <span className="text-amber-200/50">
                    {" "}· {safeDecode(sd.detail)
                      .replace(/\.pdf$/i, "")
                      .replace(/[-_]/g, " ")
                      .slice(0, 44)}
                  </span>
                )}
              </div>
              {/* Bar kemajuan nyata + ETA — dari done/total backend,
                  bukan animasi pura-pura */}
              <div className="mt-1 pl-3">
                {pct != null && (
                  <div className="h-[3px] w-56 overflow-hidden rounded-[1px] bg-amber-950/60">
                    <div
                      className="h-full bg-amber-400/75 transition-all duration-700"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                )}
                <div className="mt-[3px] tracking-wider text-amber-200/40">
                  {pct != null
                    ? `${sd.done}/${sd.total} · ${pct}%`
                    : "berjalan…"}
                  {sd.eta_s != null && ` · sisa ±${fmtDur(sd.eta_s)}`}
                  {sd.elapsed_s > 3 && ` · ${fmtDur(sd.elapsed_s)} berlalu`}
                </div>
              </div>
            </div>
          );
        })()}
        {feed.recent.length > 0 && (
          <div className="mt-4 text-[10px] leading-4">
            <div className="tracking-widest text-emerald-300/45">
              ▸ BARU DIPELAJARI
            </div>
            {feed.recent.slice(0, 4).map((d, i) => (
              <div
                key={i}
                className={`pl-3 ${
                  i === 0 ? "text-emerald-300/90" : "text-emerald-200/40"
                }`}
              >
                {i === 0 ? "●" : "○"} {d.name.slice(0, 34)}
                {d.articles > 0 && (
                  <span className="text-emerald-200/30">
                    {" "}· {d.articles} pasal
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
        {feed.queue.length > 0 && (
          <div className="mt-4 text-[10px] leading-4">
            <div className="tracking-widest text-emerald-300/45">
              ▸ RENCANA BERIKUTNYA
            </div>
            {feed.queue.slice(0, 4).map((q, i) => (
              <div key={i} className="pl-3 text-emerald-200/30">
                ◌ {q.topic}
                <span className="text-emerald-200/20">
                  {" "}
                  · {Math.round(q.score * 100)}%
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Isi otak — ringkas per wilayah; mengambil SISA ruang kolom
            (flex-1) dengan fade di bawah — tak pernah menimpa HUD */}
        <div className="mt-5 shrink-0 tracking-widest text-emerald-300/45">
          ISI OTAK
        </div>
        <div
          className="mt-1 min-h-0 flex-1 space-y-[3px] overflow-hidden text-[10px] leading-4"
          style={{
            maskImage:
              "linear-gradient(to bottom, black 70%, transparent 100%)",
            WebkitMaskImage:
              "linear-gradient(to bottom, black 70%, transparent 100%)",
          }}
        >
          {nodes.map((n, i) => {
            const name = (n.subcategory || n.category).toUpperCase();
            const laws = n.laws ?? [];
            return (
              <div key={i} className="text-emerald-200/30">
                <span
                  className={
                    laws.length
                      ? "text-glow-dim text-emerald-300/85"
                      : "text-emerald-200/30"
                  }
                >
                  {name}
                </span>
                <span className="text-emerald-200/25">
                  {" "}
                  {laws.length
                    ? `${laws.length} dok · ${Math.round(
                        (n.knowledge_score ?? 0) * 100
                      )}%`
                    : "∅"}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* HUD metrik */}
      <div className="font-term absolute bottom-6 left-6 select-none text-[12px] leading-6 text-emerald-300/80">
        <div className="mb-1 flex items-center gap-2">
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              learning ? "animate-pulse bg-amber-400" : "bg-emerald-400"
            }`}
          />
          <span className="tracking-widest">
            {learning ? "BELAJAR — AKUISISI PENGETAHUAN" : "SIAP — PENGETAHUAN CUKUP"}
          </span>
        </div>
        <div>
          pemahaman hukum{" "}
          <span className="text-emerald-200">{score}%</span>
        </div>
        <div>
          undang-undang{" "}
          <span className="text-emerald-200">{alcd?.laws_ingested ?? 0}</span>
          {"  ·  "}sinaps (pasal){" "}
          <span className="text-emerald-200">{alcd?.total_chunks ?? 0}</span>
        </div>
        <div>
          wilayah ontologi{" "}
          <span className="text-emerald-200">{alcd?.ontology_nodes ?? 0}</span>
          {"  ·  "}celah terbuka{" "}
          <span className="text-amber-300/80">{alcd?.unresolved_gaps ?? 0}</span>
        </div>
      </div>

      {/* Terminal aktivitas — kanan bawah; tinggi mengikuti isi,
          maksimal ~¼ halaman; baris lama memudar */}
      <div className="corner-ticks absolute bottom-6 right-6 flex max-h-[27vh] w-[430px] select-none flex-col overflow-hidden rounded-[2px] border border-emerald-400/15 bg-black/50 font-mono text-[11px] leading-5 shadow-[0_0_34px_rgba(74,255,158,0.07)] backdrop-blur-sm">
        <i className="ct ct-tl" /><i className="ct ct-tr" />
        <i className="ct ct-bl" /><i className="ct ct-br" />
        <div className="flex items-center gap-2 border-b border-emerald-400/10 px-3 py-1.5">
          <span className="h-2 w-2 rounded-full bg-red-500/60" />
          <span className="h-2 w-2 rounded-full bg-amber-400/60" />
          <span className="h-2 w-2 rounded-full bg-emerald-400/60" />
          <span className="ml-2 tracking-widest text-emerald-300/50">
            neural.log — aktivitas ALCD
          </span>
        </div>
        <div className="flex flex-col gap-[1px] px-3 py-2">
          {lines.slice(-11).map((l, i, arr) => {
            const isLast = i === arr.length - 1;
            const shown = isLast ? l.text.slice(0, typed) : l.text;
            /* Baris tertua hampir menghilang; terbaru penuh terang */
            const fade = arr.length <= 1 ? 1 : 0.22 + 0.78 * (i / (arr.length - 1));
            return (
              <div
                key={l.id}
                className="flex gap-2 whitespace-nowrap"
                style={{ opacity: isLast ? 1 : fade }}
              >
                <span className="text-emerald-200/25">{l.ts}</span>
                <span className={`w-[52px] shrink-0 ${TAG_CLS[l.kind]}`}>
                  [{l.tag}]
                </span>
                <span className={KIND_CLS[l.kind]}>
                  {shown}
                  {isLast && (
                    <span className="caret-blink ml-0.5 text-emerald-300">
                      ▊
                    </span>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Toggle layar penuh */}
      <button
        onClick={toggleFullscreen}
        title="Layar penuh (tekan F)"
        className="font-term absolute left-1/2 top-6 -translate-x-1/2 select-none border border-emerald-400/20 bg-black/40 px-2 py-0.5 text-[10px] tracking-widest text-emerald-300/50 hover:border-emerald-300/50 hover:text-emerald-200"
      >
        {isFs ? "[ ⛶ KELUAR ]" : "[ ⛶ LAYAR PENUH · F ]"}
      </button>

      <div className="font-term absolute bottom-6 left-1/2 -translate-x-1/2 select-none text-[10px] tracking-widest text-emerald-200/25">
        NOL DATA → DIPEROLEH OTONOM · APH INDONESIA
      </div>
    </div>
  );
}
