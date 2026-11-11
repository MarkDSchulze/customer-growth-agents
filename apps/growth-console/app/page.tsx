'use client';
import Link from 'next/link';
import EnterpriseWorkspace from './enterprise';
import {useCallback, useEffect, useState} from 'react';
import {Activity, ArrowRight, ArrowUpRight, BarChart3, Check, ChevronRight,
  CircleHelp, Command, GitBranch, Layers3, LayoutDashboard, LockKeyhole, Megaphone,
  MessageCircle, Pause, Play, Radio, RefreshCw, Search, ShieldCheck,
  ShoppingBag, Sparkles, Target, Users, X} from 'lucide-react';

type Workflow = {workflowId:string; cartId:string; customerRef:string; correlationId:string;
  state:string; reasonCodes:string[]; startedAt:string; policyVersion:string};
type Audit = {sequence:number; operation:string; outcome:string; workflowId:string; at:string; policyVersion:string};
type Decision = {disposition:string; reasonCodes:string[]; contextHash:string; rankerVersion:string;
  proposals:{domain:string; tool:string; rationale:string[]}[]};
type Cohort = {n:number; conversions:number; conversionRate:number|null};
type Report = {exposures:number; absoluteLift:number|null; conservative95Interval:number[]|null;
  cohorts:{control:Cohort; treatment:Cohort}; interpretation:string};
type Status = {tenantId:string; killSwitch:boolean; mode:string; execution:string; policy:{version:string; dryRun:boolean; holdoutFraction:number}};
const navigation = ['Overview', 'Orchestration', 'Enterprise workflows', 'Connectors', 'Experiments', 'Governance', 'Activity log'] as const;
type Tab = typeof navigation[number];
const navIcons = [LayoutDashboard, GitBranch, Layers3, Target, BarChart3, ShieldCheck, Activity];
const domains = [
  {name:'Marketing', icon:Megaphone, color:'violet', description:'Approved journey orchestration', tools:'1 governed tool'},
  {name:'Advertising', icon:Target, color:'orange', description:'Audience and media recommendations', tools:'Recommendations only'},
  {name:'Sales', icon:Users, color:'blue', description:'Seller opportunity planning', tools:'Recommendations only'},
  {name:'Commerce', icon:ShoppingBag, color:'teal', description:'Cart, order and inventory context', tools:'Read-only context'},
  {name:'Service', icon:MessageCircle, color:'pink', description:'Customer health and suppression', tools:'Read-only context'},
];
const terminal = new Set(['SUPPRESSED','HOLDOUT','COMPLETED','EXPIRED','CANCELLED','FAILED_REVIEW','DRY_RUN']);
const label = (s:string) => s.toLowerCase().replaceAll('_',' ');
const rate = (n:number|null|undefined) => n == null ? '—' : `${(n*100).toFixed(1)}%`;

export default function Home() {
  const [tab,setTab] = useState<Tab>('Overview');
  const [token,setToken] = useState('');
  const [draft,setDraft] = useState('');
  const [connecting,setConnecting] = useState(false);
  const [status,setStatus] = useState<Status|null>(null);
  const [workflows,setWorkflows] = useState<Workflow[]>([]);
  const [audits,setAudits] = useState<Audit[]>([]);
  const [report,setReport] = useState<Report|null>(null);
  const [selected,setSelected] = useState<Workflow|null>(null);
  const [decision,setDecision] = useState<Decision|null>(null);
  const [query,setQuery] = useState('');
  const [error,setError] = useState('');
  const [busy,setBusy] = useState(false);
  const [confirmKill,setConfirmKill] = useState(false);
  const [updated,setUpdated] = useState('');
  const [help,setHelp] = useState(false);

  const api = useCallback(async <T,>(path:string, method='GET', body?:unknown):Promise<T> => {
    const response = await fetch(`/api/growth/v1/${path}`, {
      method, headers:{'Authorization':`Bearer ${token}`, 'Content-Type':'application/json'},
      body:body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await response.json();
    if(!response.ok) throw new Error(data.detail ?? 'Request failed');
    return data as T;
  },[token]);
  const refresh = useCallback(async () => {
    if(!token) return;
    const [s,w,r,a] = await Promise.all([api<Status>('status'),api<Workflow[]>('workflows'),
      api<Report>('experiments/report'),api<Audit[]>('audit')]);
    setStatus(s);setWorkflows(w);setReport(r);setAudits(a);setError('');
    setUpdated(new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}));
  },[api,token]);
  useEffect(() => {
    if(!token) return;
    let active = true;
    const load = () => refresh().catch(e => {if(active) setError(String(e.message));});
    load(); const timer=setInterval(load,8000);
    return () => {active=false;clearInterval(timer);};
  },[token,refresh]);
  useEffect(() => {
    if(!selected && !confirmKill && !help) return;
    const before=document.activeElement as HTMLElement|null;
    const handler=(e:KeyboardEvent) => {
      if(e.key==='Escape'){setSelected(null);setConfirmKill(false);setHelp(false);}
      if(e.key==='Tab'){
        const dialog=document.querySelector('[role="dialog"]');
        const items=Array.from(dialog?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input')??[]);
        const first=items[0], last=items[items.length-1];
        if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}
        else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}
      }
    };
    document.addEventListener('keydown',handler);
    return () => {document.removeEventListener('keydown',handler);before?.focus();};
  },[selected,confirmKill,help]);
  async function connect() {
    setConnecting(true);setError('');
    try {
      const response=await fetch('/api/growth/v1/status',{headers:{Authorization:`Bearer ${draft.trim()}`}});
      const data=await response.json();
      if(!response.ok) throw new Error(data.detail);
      setToken(draft.trim());setDraft('');setStatus(data);
    } catch(e) {setError(e instanceof Error ? e.message : 'Connection failed');}
    finally {setConnecting(false);}
  }
  async function runDemo() {
    setBusy(true);setError('');
    try {
      await api('simulation/enable','POST');
      for (let i=0;i<8;i++) {
        const cartId=`cart-demo-${i.toString().padStart(3,'0')}`, customerRef=`cust-demo-${i.toString().padStart(3,'0')}`;
        await api('simulation/context','PUT',{cartId,customerRef,consent:i!==2,severeCase:i===1,inStock:i!==3});
        await api('events','POST',{
          eventId:crypto.randomUUID(),eventType:'commerce.cart_abandoned.v1',tenantId:status?.tenantId,
          aggregateId:cartId,occurredAt:new Date().toISOString(),correlationId:crypto.randomUUID(),
          source:'growth-console-demo',data:{cartId,customerRef,cartValue:'120.00',currency:'USD',itemIds:['sku-demo-01']},
        });
      }
      await refresh();
    } catch(e) {setError(e instanceof Error ? e.message : 'Demo failed');}
    finally {setBusy(false);}
  }
  async function toggleKill() {
    setBusy(true);
    try {await api('control/kill-switch','PUT',{enabled:!status?.killSwitch});setConfirmKill(false);await refresh();}
    catch(e){setError(e instanceof Error ? e.message : 'Control failed');}
    finally{setBusy(false);}
  }
  async function selectWorkflow(w:Workflow) {
    setSelected(w);setDecision(null);
    try{setDecision(await api<Decision>(`decisions/${w.workflowId}`));}
    catch{setDecision(null);}
  }
  async function command(action:'cancel'|'replay') {
    if(!selected) return;
    setBusy(true);
    try{await api(`workflows/${selected.workflowId}/${action}`,'POST');await refresh();setSelected(null);}
    catch(e){setError(e instanceof Error ? e.message : 'Command failed');}
    finally{setBusy(false);}
  }
  const suppressed=workflows.filter(w=>w.state==='SUPPRESSED').length;
  const active=workflows.filter(w=>!terminal.has(w.state)).length;
  const filtered=workflows.filter(w=>`${w.cartId} ${w.state} ${w.reasonCodes.join(' ')}`.toLowerCase().includes(query.toLowerCase()));

  return <div className="shell">
    <a className="skip" href="#main">Skip to content</a>
    <aside className="sidebar">
      <Link href="/" className="brand"><span className="brand-mark"><Layers3 size={22}/></span>growth<span className="brand-os">os</span><span className="brand-dot"/></Link>
      <div className="workspace"><div className="workspace-icon">G</div><div><strong>Growth workspace</strong><span>{status?.tenantId ?? 'Local environment'}</span></div><ChevronRight size={15}/></div>
      <div className="nav-label">WORKSPACE</div>
      <nav aria-label="Main navigation">{navigation.map((name,i)=>{const Icon=navIcons[i];return <button key={name} className={tab===name?'nav-item current':'nav-item'} onClick={()=>setTab(name)}><Icon size={18}/>{name}{name==='Orchestration'&&<span className="nav-count">{workflows.length}</span>}</button>;})}</nav>
      <div className="sidebar-bottom"><div className="safety-card"><ShieldCheck size={23}/><strong>Governed by design</strong><p>Every action passes deterministic policy controls.</p><span><i/>Synthetic environment</span></div><button className="nav-item" onClick={()=>setHelp(true)}><CircleHelp size={18}/>Documentation <ArrowUpRight size={14}/></button><div className="profile"><div className="avatar">LO</div><div><strong>Local operator</strong><span>{token?'Connected session':'Authentication required'}</span></div><LockKeyhole size={14}/></div></div>
    </aside>
    <div className="main-wrap">
      <header className="topbar"><div className="breadcrumb">Workspace <ChevronRight size={14}/><strong>{tab}</strong></div><div className="top-actions"><span className="env-pill"><i/>SYNTHETIC</span><button className="icon-button" aria-label="Help" onClick={()=>setHelp(true)}><CircleHelp size={18}/></button><div className="avatar small">LO</div></div></header>
      <main id="main">
        <div className="page-heading"><div><div className="eyebrow">CUSTOMER GROWTH INTELLIGENCE</div><h1>{tab==='Overview'?'Growth command center':tab}</h1><p>One orchestration layer. Every customer interaction, coordinated.</p></div><div className="heading-actions"><button className="button subtle" disabled={!token||busy} onClick={()=>refresh().catch(e=>setError(e.message))}><RefreshCw size={15}/>Refresh</button>{!["Enterprise workflows","Connectors"].includes(tab)&&<button className="button primary" disabled={!token||busy} onClick={runDemo}><Play size={14}/>{busy?'Working…':'Run synthetic demo'}</button>}</div></div>
        {error&&<div className="error" role="alert">{label(error)}<button aria-label="Dismiss error" onClick={()=>setError('')}><X size={16}/></button></div>}
        {!token&&<section className="connection"><div className="connection-icon"><LockKeyhole size={22}/></div><div><h2>Connect your local workspace</h2><p>Run <code>make token</code> and enter the short-lived local token. Your token stays in memory for this session.</p><form onSubmit={e=>{e.preventDefault();void connect();}}><label className="sr-only" htmlFor="token">Local access token</label><input id="token" type="password" placeholder="Paste local access token" value={draft} onChange={e=>setDraft(e.target.value)} autoComplete="off" required/><button className="button primary" disabled={connecting}>{connecting?'Connecting…':'Connect workspace'}<ArrowRight size={15}/></button></form></div></section>}
        {token&&<div className="live-strip"><span><i className={status?.killSwitch?'dot red':'dot'}/>{status?.killSwitch?'Outbound actions paused':'Policy controls active'}<span className="strip-divider"/>{status?.policy.version}<span className="strip-divider"/>Mock adapters only</span><small>Updated {updated}</small></div>}
        {(tab==='Enterprise workflows'||tab==='Connectors')&&<EnterpriseWorkspace token={token} connectorsOnly={tab==='Connectors'}/>}
        {(tab==='Overview'||tab==='Experiments')&&<>
          <section className="metrics" aria-label="Growth metrics">
            {[{name:'Orchestrated journeys',value:workflows.length,detail:'Across service-aware cart recovery',icon:GitBranch},
              {name:'Confirmed mock exposures',value:report?.exposures??0,detail:'Idempotent, approved activations',icon:Radio},
              {name:'Policy suppressions',value:suppressed,detail:'Customer protections enforced',icon:ShieldCheck},
              {name:'Observed conversion lift',value:rate(report?.absoluteLift),detail:'Treatment minus control · descriptive',icon:BarChart3}].map(m=><article className="metric" key={m.name}><div className="metric-top">{m.name}<m.icon size={17}/></div><strong>{token?m.value:'—'}</strong><p>{m.detail}</p></article>)}
          </section>
          {tab==='Overview'&&<section className="agents-section"><div className="section-heading"><div><h2>Specialists, working together <span className="count">5</span></h2><p>Bounded domain agents. Shared context. Central policy enforcement.</p></div><span className="text-tag"><Sparkles size={13}/>Deterministic baseline</span></div><div className="agent-grid">{domains.map(d=><article className="agent-card" key={d.name}><div className="agent-top"><span className={`domain-icon ${d.color}`}><d.icon size={20}/></span><span className="agent-status"><i/>Available</span></div><h3>{d.name}</h3><p>{d.description}</p><div className="agent-footer"><span>{d.tools}</span><ArrowUpRight size={14}/></div></article>)}</div></section>}
          <div className="two-col"><section className="panel experiment-panel"><div className="panel-heading"><div><h2>Recovery experiment</h2><p>Customer-level randomized holdout</p></div><span className="badge blue">Synthetic</span></div><div className="experiment-chart">{(['treatment','control'] as const).map(arm=><div className="cohort" key={arm}><div><strong>{arm==='treatment'?'Treatment':'Control'}</strong><span>{report?.cohorts[arm].n??0} customers</span></div><div className="bar-track"><div className={`bar ${arm}`} style={{width:`${Math.max(0,(report?.cohorts[arm].conversionRate??0)*100)}%`}}/></div><strong>{rate(report?.cohorts[arm].conversionRate)}</strong></div>)}</div><div className="chart-note"><Activity size={14}/><span>Small samples. Observation windows may be incomplete. Attributed revenue is not incremental revenue.</span></div></section><section className="panel protection-panel"><div className="panel-heading"><div><h2>Execution guardrails</h2><p>Validated immediately before activation</p></div><ShieldCheck size={20}/></div><div className="guardrail-list">{['Purpose & channel consent','Service health & order status','Approved journey & frequency cap','Stable assignment & idempotency'].map(g=><div key={g}><span className="check-icon"><Check size={12}/></span>{g}<span className="enforced">Enforced</span></div>)}</div></section></div>
        </>}
        {(tab==='Overview'||tab==='Orchestration')&&<section className="panel journeys-panel"><div className="panel-heading"><div><h2>Journey orchestration <span className="count">{workflows.length}</span></h2><p>From customer signal to governed outcome</p></div><label className="search"><Search size={15}/><input placeholder="Search journeys…" aria-label="Search journeys" value={query} onChange={e=>setQuery(e.target.value)}/></label></div><div className="table-scroll"><table><thead><tr><th>JOURNEY / CUSTOMER</th><th>WORKFLOW STATUS</th><th>POLICY OUTCOME</th><th>STARTED</th><th><span className="sr-only">View details</span></th></tr></thead><tbody>{filtered.slice().reverse().map(w=><tr key={w.workflowId} onClick={()=>selectWorkflow(w)}><td><div className="journey-cell"><span className="journey-icon"><ShoppingBag size={17}/></span><div><strong>Cart recovery</strong><small>{w.cartId} · {w.customerRef}</small></div></div></td><td><span className={`badge ${['AWAITING_OUTCOME','COMPLETED'].includes(w.state)?'green':w.state==='SUPPRESSED'?'amber':w.state==='FAILED_REVIEW'?'rose':'blue'}`}><i/>{label(w.state)}</span></td><td className="reason">{label(w.reasonCodes[0]??'pending')}</td><td className="time">{new Date(w.startedAt).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}</td><td><button className="icon-button" aria-label={`Inspect ${w.cartId}`} onClick={e=>{e.stopPropagation();void selectWorkflow(w);}}><ChevronRight size={17}/></button></td></tr>)}</tbody></table>{!filtered.length&&<div className="empty"><GitBranch size={26}/><h3>Your journeys start here</h3><p>{token?'Run the synthetic demo to see eligible, suppressed and holdout journeys.':'Connect your workspace to inspect orchestration.'}</p></div>}</div><div className="table-footer"><span>{workflows.length} journeys · {active} awaiting progress</span><span>Service-aware cart recovery <ArrowRight size={13}/></span></div></section>}
        {tab==='Governance'&&<section className="panel governance"><ShieldCheck size={32}/><h2>Execution policy</h2><p>Consent, service status, order eligibility and authorization always take precedence over agent proposals.</p><dl><dt>Policy version</dt><dd>{status?.policy.version??'—'}</dd><dt>Default mode</dt><dd>Observe only; mock execution requires explicit enablement</dd><dt>Journey allowlist</dt><dd>cart-recovery-v1</dd><dt>Control allocation</dt><dd>{rate(status?.policy.holdoutFraction)}</dd><dt>Frequency cap</dt><dd>One approved activation per customer per 24 hours</dd><dt>Action authority</dt><dd>Marketing: approved journey. Other domains: recommendations only.</dd></dl><button className="button danger" disabled={!token} onClick={()=>setConfirmKill(true)}><Pause size={15}/>{status?.killSwitch?'Resume tenant actions':'Pause all tenant actions'}</button></section>}
        {tab==='Activity log'&&<section className="panel"><div className="panel-heading"><div><h2>Correlated audit trail</h2><p>Append-only operational metadata, scoped to your authenticated tenant</p></div><Activity size={18}/></div><div className="audit-list">{audits.length?audits.map(a=><div className="audit-row" key={a.sequence}><span className="audit-dot"/><div><strong>{a.operation}</strong><span>{label(a.outcome)}</span></div><small>{a.policyVersion}</small><time>{new Date(a.at).toLocaleTimeString()}</time></div>):<div className="empty">No audit events yet.</div>}</div></section>}
        <footer className="page-footer"><span><ShieldCheck size={13}/>Synthetic reference implementation · No live customer contact</span><span>Growth OS <span className="footer-dot">•</span> v0.2.0</span></footer>
      </main>
    </div>
    {selected&&<div className="modal-backdrop" onClick={()=>setSelected(null)}><section className="drawer" role="dialog" aria-modal="true" aria-label="Journey details" onClick={e=>e.stopPropagation()}><button autoFocus className="close icon-button" aria-label="Close details" onClick={()=>setSelected(null)}><X size={20}/></button><div className="eyebrow">WORKFLOW INSPECTOR</div><h2>{selected.cartId}</h2><span className="badge blue">{label(selected.state)}</span><dl><dt>Customer reference</dt><dd>{selected.customerRef}</dd><dt>Correlation ID</dt><dd className="mono">{selected.correlationId}</dd><dt>Workflow ID</dt><dd className="mono">{selected.workflowId}</dd><dt>Policy reasons</dt><dd>{selected.reasonCodes.map(label).join(', ')}</dd><dt>Decision</dt><dd>{decision?.disposition??'Pending'}</dd></dl><h3>Domain proposals</h3>{decision?.proposals.map(p=><div className="proposal" key={p.domain}><strong>{p.domain}</strong><span>{label(p.tool)}</span><small>{p.rationale.map(label).join(', ')}</small></div>)}<div className="drawer-actions"><button className="button subtle" disabled={busy||terminal.has(selected.state)} onClick={()=>command('cancel')}>Cancel workflow</button>{selected.state==='FAILED_REVIEW'&&<button className="button primary" disabled={busy} onClick={()=>command('replay')}>Recheck & replay</button>}</div></section></div>}
    {confirmKill&&<div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="kill-title"><ShieldCheck size={30}/><h2 id="kill-title">{status?.killSwitch?'Resume mock execution?':'Pause tenant execution?'}</h2><p>{status?.killSwitch?'Eligible workflows can activate approved mock journeys after all policies are rechecked.':'This blocks every new outbound action for your tenant. Existing accepted actions remain recorded.'}</p><div className="modal-actions"><button autoFocus className="button subtle" onClick={()=>setConfirmKill(false)}>Keep current state</button><button className="button danger" disabled={busy} onClick={toggleKill}>{status?.killSwitch?'Resume actions':'Pause actions'}</button></div></section></div>}
    {help&&<div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-label="Local setup help"><button autoFocus className="close icon-button" aria-label="Close help" onClick={()=>setHelp(false)}><X size={18}/></button><Command size={28}/><h2>Start your growth workspace</h2><p>From the repository, run:</p><pre>make setup{'\n'}make dev{'\n'}make token</pre><p>Connect with the generated token, then run the synthetic demo. Inspect journey details, compare cohorts, and control the tenant kill switch in Governance.</p><a href="https://github.com/MarkDSchulze/customer-growth-agents" target="_blank" rel="noreferrer" className="button primary">Repository & runbook<ArrowUpRight size={15}/></a></section></div>}
  </div>;
}
