"use client";

import Link from "next/link";
import { ArrowRight, Bell, BookOpenCheck, Check, ClipboardCheck, Compass, FileCheck2, Menu, Play, ShieldCheck } from "lucide-react";
import { useState } from "react";
import styles from "./v4.module.css";

const steps = [
  { title: "Foundation", detail: "12 points recorded", state: "done" },
  { title: "Broaden practice", detail: "1 category left", state: "current" },
  { title: "Confirm evidence", detail: "Starts 15 Jun", state: "upcoming" },
  { title: "Submit", detail: "Due 30 Jun", state: "upcoming" },
];

export default function ProgressNavigator() {
  const [started, setStarted] = useState(false);

  return (
    <main className={styles.page}>
      <header className={styles.mobileHeader}>
        <Link href="/" className={styles.brand}><span>+</span> Care Credits</Link>
        <button aria-label="Open navigation"><Menu /></button>
      </header>
      <aside className={styles.sidebar}>
        <Link href="/" className={styles.brand}><span>+</span> Care Credits</Link>
        <p>APC 2026</p>
        <nav>
          <a className={styles.active} href="#pathway"><Compass /> My pathway</a>
          <a href="#requirements"><ClipboardCheck /> Requirements</a>
          <a href="#evidence"><FileCheck2 /> Evidence locker</a>
          <a href="#submit"><ShieldCheck /> Submit renewal</a>
        </nav>
        <div className={styles.profile}><small>Signed in as</small><strong>Dr. Sarah Chen</strong><span>General Practice</span></div>
      </aside>

      <section className={styles.content} id="pathway">
        <header className={styles.topbar}>
          <div><p>APC 2026 · 48 days remaining</p><h1>A clear path, one meaningful move at a time.</h1></div>
          <div className={styles.actions}><Link href="/v3">View V3</Link><button aria-label="Notifications"><Bell /></button><span>SC</span></div>
        </header>
        <p className={styles.lede}>Your renewal pathway keeps the full requirement visible while focusing your attention where it counts.</p>

        <section className={styles.pathway} id="requirements" aria-label="Renewal pathway">
          <div className={styles.sectionHeading}><div><p>YOUR RENEWAL PATHWAY</p><h2>Four stages to a confident submission</h2></div><span><Check /> On track</span></div>
          <ol className={styles.steps}>
            {steps.map((step, index) => <li className={styles[step.state]} key={step.title}><i>{step.state === "done" ? <Check /> : index + 1}</i><div><strong>{step.title}</strong><small>{step.detail}</small></div></li>)}
          </ol>
        </section>

        <section className={styles.focusGrid}>
          <article className={styles.focusCard}>
            <div className={styles.focusKicker}><span><BookOpenCheck /></span><p>TODAY&apos;S FOCUS</p></div>
            <h2>Complete Cultural Safety</h2>
            <p>45 minutes of focused learning earns your final Category E point and moves the pathway forward.</p>
            <div className={styles.focusTags}><span>45 min</span><span>Online</span><span>+1 CPD point</span></div>
            <button onClick={() => setStarted(!started)}>{started ? <><Check /> Module added to your plan</> : <><Play /> Start module</>}<ArrowRight /></button>
          </article>
          <article className={styles.healthCard}>
            <p>PATHWAY HEALTH</p><strong>60%</strong><div className={styles.bar}><i /></div>
            <span>{started ? "Your next step is scheduled." : "Two focused sessions keep you on track."}</span>
            <div className={styles.healthMeta}><div><b>12</b><small>points logged</small></div><div><b>2</b><small>gaps remaining</small></div></div>
          </article>
        </section>

        <section className={styles.nextSteps} id="evidence">
          <div><p>WHAT&apos;S AHEAD</p><h2>Your path after today</h2></div>
          <div className={styles.nextList}>
            <article><i>01</i><div><strong>Log your module completion</strong><span>Immediately after the course</span></div><b>Next</b></article>
            <article><i>02</i><div><strong>Choose a leadership activity</strong><span>Earn 2–3 Category D points</span></div><b>By 15 Jun</b></article>
            <article id="submit"><i>03</i><div><strong>Review evidence and submit</strong><span>Everything you need is collected here</span></div><b>30 Jun</b></article>
          </div>
        </section>
      </section>
    </main>
  );
}
