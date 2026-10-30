"use client";

import Link from "next/link";
import { Bell, CalendarPlus, Check, ChevronLeft, ChevronRight, Clock3, Menu, Sparkles } from "lucide-react";
import { useState } from "react";
import styles from "./v3.module.css";

const calendarDays = ["4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29", "30", "31"];

export default function RenewalPlanner() {
  const [added, setAdded] = useState(false);

  return (
    <main className={styles.page}>
      <aside className={styles.sidebar}>
        <Link href="/" className={styles.brand}><span>+</span> Care Credits</Link>
        <p>APC 2026</p>
        <nav><a className={styles.active} href="#plan"><CalendarPlus /> Renewal planner</a><a href="#calendar"><Clock3 /> My calendar</a><a href="#milestones"><Check /> Milestones</a></nav>
        <div className={styles.profile}><small>Signed in as</small><strong>Dr. Sarah Chen</strong><span>General Practice</span></div>
      </aside>

      <section className={styles.content} id="plan">
        <header className={styles.topbar}><button className={styles.menu} aria-label="Open menu"><Menu /></button><div><p>APC 2026 · 48 days remaining</p><h1>Plan the path to renewal.</h1></div><div className={styles.actions}><Link href="/v2">View V2</Link><button aria-label="Notifications"><Bell /></button><span>SC</span></div></header>
        <p className={styles.lede}>Your calendar turns the next two months into a plan that feels achievable.</p>

        <div className={styles.layout}>
          <section className={styles.calendarCard} id="calendar">
            <div className={styles.month}><button aria-label="Previous month"><ChevronLeft /></button><div><p>RENEWAL SCHEDULE</p><h2>May 2026</h2></div><button aria-label="Next month"><ChevronRight /></button></div>
            <div className={styles.weekdays}>{["M", "T", "W", "T", "F", "S", "S"].map((day, index) => <span key={`${day}-${index}`}>{day}</span>)}</div>
            <div className={styles.days}>{calendarDays.map((day) => <div className={`${styles.day} ${day === "12" ? styles.today : ""} ${day === "15" || day === "19" ? styles.event : ""} ${day === "26" ? styles.complete : ""}`} key={day}><b>{day}</b>{day === "12" && <small>Today</small>}{day === "15" && <small>Forum</small>}{day === "19" && <small>Module</small>}{day === "26" && <small>+1 pt</small>}</div>)}</div>
            <div className={styles.legend}><span><i className={styles.todayKey} /> Today</span><span><i className={styles.eventKey} /> Learning</span><span><i className={styles.completeKey} /> Points recorded</span></div>
          </section>

          <aside className={styles.nextCard}>
            <div className={styles.nextHeader}><span><Sparkles /></span><p>NEXT UP</p></div>
            <h2>Cultural safety module</h2><p className={styles.detail}>A short online module that closes your final Category E point.</p>
            <div className={styles.tags}><b>45 min</b><b>Online</b><b>+1 CPD point</b></div>
            <button className={styles.primary} onClick={() => setAdded(!added)}>{added ? <><Check /> Added to 19 May</> : <><CalendarPlus /> Add to calendar</>}</button>
            <div className={styles.miniMetrics}><div><strong>12<span>/20</span></strong><small>points logged</small></div><div><strong>2</strong><small>gaps remaining</small></div></div>
          </aside>
        </div>

        <section className={styles.milestones} id="milestones"><div className={styles.sectionTitle}><div><p>YOUR MILESTONES</p><h2>From today to submission</h2></div><span>On track</span></div><ol><li className={styles.done}><i><Check /></i><div><strong>12 points recorded</strong><small>Current progress</small></div><em>Today</em></li><li className={added ? styles.done : styles.current}><i>{added ? <Check /> : "2"}</i><div><strong>Complete Cultural Safety</strong><small>Earn your final Category E point</small></div><em>19 May</em></li><li><i>3</i><div><strong>Join a leadership activity</strong><small>Earn 2–3 Category D points</small></div><em>By 15 Jun</em></li><li><i>4</i><div><strong>Submit APC renewal</strong><small>Review evidence and submit</small></div><em>30 Jun</em></li></ol></section>
      </section>
    </main>
  );
}
