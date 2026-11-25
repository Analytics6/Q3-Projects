"use client";

import { FormEvent, useState } from "react";
import { ArrowRight, BadgeCheck, BookOpenCheck, Eye, EyeOff, ShieldCheck, Sparkles } from "lucide-react";
import { api } from "@/lib/api";

type AuthUser = { id: string; name: string; email: string; role: string };

export default function Login() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const result = await api<{ user: AuthUser }>(`/api/auth/${mode}`, {
        method: "POST",
        body: JSON.stringify({ name, email, password }),
      });
      window.location.assign(result.user.role === "admin" ? "/?view=overview" : "/");
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : "Unable to sign in. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-story">
        <a className="brand brand-light" href="/" aria-label="Finwell home"><span className="brand-mark"><Sparkles size={17} /></span><span>finwell<span className="brand-dot">.</span></span></a>
        <div className="story-content">
          <div className="eyebrow eyebrow-light"><span className="pulse-dot" /> YOUR FINANCIAL LIFE, MADE CLEARER</div>
          <h1>Good answers.<br /><span>More peace of mind.</span></h1>
          <p>Get a clear next step for card and loan questions, supported by helpful references and practical guidance.</p>
          <div className="story-cards">
            <div className="story-card"><span className="story-icon"><BookOpenCheck size={17} /></span><div><strong>Answers with sources</strong><span>Helpful references with every reply</span></div></div>
            <div className="story-card"><span className="story-icon"><ShieldCheck size={17} /></span><div><strong>Designed for privacy</strong><span>Your conversations stay in your account</span></div></div>
          </div>
        </div>
        <div className="auth-story-foot"><span>© 2026 Finwell Support</span><span>Cards · Home loans · Personal loans</span></div>
      </section>
      <section className="auth-panel">
        <div className="auth-panel-top"><span>Secure customer workspace</span><span className="secure-label"><BadgeCheck size={14} /> Protected sign in</span></div>
        <div className="auth-form-wrap">
          <div className="auth-heading"><div className="auth-mark"><Sparkles size={18} /></div><h2>{mode === "login" ? "Welcome back" : "Create your account"}</h2><p>{mode === "login" ? "Sign in to continue your support conversation." : "A calmer way to work through a banking question."}</p></div>
          <form className="auth-form" onSubmit={submit}>
            {mode === "register" && <label>Your name<input value={name} onChange={(event) => setName(event.target.value)} autoComplete="name" placeholder="e.g. Asha Rao" required minLength={2} maxLength={100} /></label>}
            <label>Email address<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" placeholder="you@example.com" required /></label>
            <label>Password<div className="password-field"><input type={showPassword ? "text" : "password"} value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} placeholder={mode === "login" ? "Enter your password" : "At least 12 characters"} minLength={mode === "register" ? 12 : 1} required /><button type="button" className="icon-button password-toggle" onClick={() => setShowPassword(!showPassword)} aria-label={showPassword ? "Hide password" : "Show password"}>{showPassword ? <EyeOff size={17} /> : <Eye size={17} />}</button></div></label>
            {error && <div className="form-error" role="alert">{error}</div>}
            <button className="primary-button auth-submit" disabled={busy}>{busy ? <span className="spinner" /> : <>{mode === "login" ? "Sign in" : "Create account"}<ArrowRight size={16} /></>}</button>
          </form>
          <div className="auth-switch">{mode === "login" ? "New to Finwell?" : "Already have an account?"}<button onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}>{mode === "login" ? "Create an account" : "Sign in"}</button></div>
          <div className="auth-note"><ShieldCheck size={16} /><span>Never share your card number, CVV, PIN, OTP, or banking password here.</span></div>
        </div>
        <div className="auth-panel-foot"><span>General support, always grounded in references.</span><a href="https://www.rbi.org.in/" target="_blank" rel="noreferrer">RBI resources ↗</a></div>
      </section>
    </main>
  );
}
