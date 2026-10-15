"use client";

import Link from "next/link";
import { Bell, BookOpenCheck, Check, ClipboardCheck, FileCheck2, FolderOpen, Menu, Plus, ShieldCheck, Sparkles } from "lucide-react";
import { useState } from "react";
import styles from "./v5.module.css";

const evidence = [
  { title: "Practice forum reflection", meta: "15 May · Professional practice", state: "Ready" },
  { title: "Peer feedback note", meta: "10 May · Community contribution", state: "Linked" },
  { title: "Clinical update certificate", meta: "08 May · Learning & development", state: "Ready" },
];

export default function EvidenceIntelligence() {
  const [captured, setCaptured] = useState(false);

  return (
    <main className={styles.page}>
      <header className={styles.mobileHeader}><Link href="/" className={styles.brand}><span>+</span> Care Credits</Link><button aria-label="Open navigation"><Menu /></button></header>
      <aside className={styles.sidebar}>
        <Link href="/" className={styles.brand}><span>+</span> Care Credits</Link>
        <p>APC 2026</p>
        <nav><a href="#overview"><Sparkles /> Overview</a><a href="#coverage" className={styles.active}><ClipboardCheck /> Evidence coverage</a><a href="#locker"><FolderOpen /> Evidence locker</a><a href="#submit"><ShieldCheck /> Submit renewal</a></nav>
        <div className={styles.profile}><small>Signed in as</small><strong>Dr. Sarah Chen</strong><span>General Practice</span></div>
      </aside>

      <section className={styles.content} id="overview">
        <header className={styles.topbar}><div><p>APC 2026 · 48 days remaining</p><h1>Every activity, already doing its job.</h1></div><div className={styles.actions}><Link href="/v4">View V4</Link><button aria-label="Notifications"><Bell /></button><span>SC</span></div></header>
        <p className={styles.lede}>Capture the work you already do, see exactly where it helps, and build a complete renewal story before submission.</p>

        <section className={styles.coverage} id="coverage">
          <div className={styles.sectionHeading}><div><p>REQUIREMENT COVERAGE</p><h2>Evidence mapped to your APC</h2></div><span><Check /> {captured ? "New evidence captured" : "Mostly complete"}</span></div>
          <div className={styles.categoryGrid}>
            <article><span className={styles.icon}><BookOpenCheck /></span><p>Learning & development</p><strong>{captured ? "13" : "12"}<small>/20 points</small></strong><div className={styles.bar}><i style={{ width: captured ? "65%" : "60%" }} /></div><b>{captured ? "6 records" : "5 records"}</b></article>
            <article><span className={styles.icon}><FileCheck2 /></span><p>Professional practice</p><strong>3<small> records</small></strong><div className={styles.bar}><i style={{ width: "75%" }} /></div><b>1 review pending</b></article>
            <article><span className={styles.icon}><ClipboardCheck /></span><p>Community contribution</p><strong>4<small> points</small></strong><div className={styles.bar}><i style={{ width: "80%" }} /></div><b>2 records linked</b></article>
            <article className={styles.gap}><span className={styles.icon}>+1</span><p>Category E</p><strong>{captured ? "Complete" : "1 point"}<small>{captured ? "" : " gap"}</small></strong><div className={styles.bar}><i style={{ width: captured ? "100%" : "50%" }} /></div><b>{captured ? "Evidence ready" : "Cultural safety module"}</b></article>
          </div>
        </section>

        <section className={styles.workspace}>
          <article className={styles.capture}>
            <div className={styles.captureIcon}><Sparkles /></div><p>ONE SMALL CAPTURE</p><h2>{captured ? "Reflection saved to your locker." : "Turn today’s learning into renewal-ready evidence."}</h2><span>{captured ? "Your Cultural Safety reflection now strengthens both Learning & development and Category E." : "When you finish Cultural Safety, add a short reflection. We’ll file it against the right APC requirements."}</span>
            <button onClick={() => setCaptured(!captured)}>{captured ? <><Check /> Evidence captured</> : <><Plus /> Add reflection</>}</button>
          </article>
          <article className={styles.locker} id="locker"><div className={styles.lockerHeading}><div><p>EVIDENCE LOCKER</p><h2>Recent records</h2></div><button aria-label="Add evidence"><Plus /></button></div><div className={styles.records}>{(captured ? [{ title: "Cultural safety reflection", meta: "Today · Category E", state: "New" }, ...evidence] : evidence).map((item) => <div className={styles.record} key={item.title}><i><FileCheck2 /></i><div><strong>{item.title}</strong><small>{item.meta}</small></div><b className={item.state === "New" ? styles.new : ""}>{item.state}</b></div>)}</div><Link href="#submit">View all evidence →</Link></article>
        </section>

        <section className={styles.submit} id="submit"><div><p>SUBMISSION CONFIDENCE</p><h2>{captured ? "Evidence is complete enough to review." : "Your evidence is clear and well distributed."}</h2><span>{captured ? "One remaining review will prepare your final submission." : "Add the Cultural Safety reflection to lift confidence further."}</span></div><strong>{captured ? "9" : "8"}<small>/10</small></strong></section>
      </section>
    </main>
  );
}
