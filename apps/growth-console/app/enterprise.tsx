'use client';
import {useCallback,useEffect,useState} from 'react';
import {Check,ChevronRight,GitBranch,Play,RefreshCw,ShieldCheck,Link2,Download,AlertCircle} from 'lucide-react';

type Action={actionId:string;domain:string;tool:string;state:string;reasonCode:string;attempts:number;externalRef:string|null;parameters:Record<string,string>};
type Workflow={workflowId:string;customerRef:string;signal:string;purpose:string;region:string;policyVersion:string;correlationId:string;state:string;planHash:string;actions:Action[];decision:{agents:{domain:string;modelVersion:string;state:string;dependencies:string[]}[]}|null};
type Page={items:Workflow[];nextCursor:string|null};
type Organization={tenantId:string;region:string;brand:string;policyVersion:string;killSwitch:boolean;actionsPerHour:number;maxPending:number;simulationEnabled:boolean};
type Provider={provider:string;configuredProfiles:number;productionWrites?:boolean;mode?:string;activationRequirement?:string};
const human=(s:string)=>s.toLowerCase().replaceAll('_',' ');
const finished=new Set(['COMPLETED','SUPPRESSED','HOLDOUT','CANCELLED','EXPIRED','FAILED_REVIEW','DRY_RUN']);

export default function EnterpriseWorkspace({token,connectorsOnly=false}:{token:string;connectorsOnly?:boolean}){
  const [organization,setOrganization]=useState<Organization|null>(null);
  const [workflows,setWorkflows]=useState<Workflow[]>([]);
  const [status,setStatus]=useState('');
  const [customer,setCustomer]=useState('');
  const [operations,setOperations]=useState<{workflows:Record<string,number>;actions:Record<string,number>}|null>(null);
  const query=new URLSearchParams({...(status?{state:status}:{}),...(customer?{customer}:{})}).toString();
  const [cursor,setCursor]=useState<string|null>(null);
  const [selected,setSelected]=useState<Workflow|null>(null);
  const [providers,setProviders]=useState<Provider[]>([]);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const api=useCallback(async<T,>(path:string,method='GET',body?:unknown,key?:string):Promise<T>=>{
    const response=await fetch(`/api/growth/v2/${path}`,{method,headers:{Authorization:`Bearer ${token}`,
      'Content-Type':'application/json',...(key?{'Idempotency-Key':key}:{})},
      body:body===undefined?undefined:JSON.stringify(body)});
    const value=await response.json();
    if(!response.ok)throw new Error(value.detail??'Request failed');
    return value as T;
  },[token]);
  const refresh=useCallback(async()=>{
    if(!token)return;
    try{
      const [org,page,connections,metrics]=await Promise.all([api<Organization>('tenant'),api<Page>('workflows?'+query),
        api<{providers:Provider[]}>('connectors'),api<{workflows:Record<string,number>;actions:Record<string,number>}>('operations')]);
      setOperations(metrics);
      setOrganization(org);setWorkflows(page.items);setCursor(page.nextCursor);setProviders(connections.providers);setError('');
    }catch(e){setError(e instanceof Error?e.message:'Refresh failed');}
  },[api,token,query]);
  useEffect(()=>{const initial=setTimeout(()=>void refresh(),0);const timer=setInterval(()=>void refresh(),7000);return()=>{clearTimeout(initial);clearInterval(timer);};},[refresh]);
  const selectedId=selected?.workflowId;
  useEffect(()=>{if(!selectedId)return;let active=true;const timer=setInterval(()=>{void api<Workflow>(`workflows/${selectedId}`).then(value=>{if(active)setSelected(value);}).catch(()=>{if(active)setError('Workflow refresh failed');});},2000);return()=>{active=false;clearInterval(timer);};},[api,selectedId]);
  async function demo(){setBusy(true);try{await api('simulation/demo','POST');await refresh();}catch(e){setError(e instanceof Error?e.message:'Demo failed');}finally{setBusy(false);}}
  async function command(operation:string){if(!selected)return;setBusy(true);try{
    const path=`workflows/${selected.workflowId}/`;
    if(operation==='approve')await api(path+'approval','POST',{decision:'approved',planHash:selected.planHash});
    else await api(path+operation,'POST');
    if(operation!=='cancel')await api(path+'execute','POST',undefined,selected.workflowId);
    setSelected(await api<Workflow>(`workflows/${selected.workflowId}`));await refresh();
  }catch(e){setError(e instanceof Error?e.message:'Command failed');}finally{setBusy(false);}}
  async function more(){if(!cursor)return;const page=await api<Page>('workflows?'+query+'&cursor='+encodeURIComponent(cursor));setWorkflows(old=>[...old,...page.items]);setCursor(page.nextCursor);}
  async function exportAudit(){try{const response=await fetch('/api/growth/v2/audit/export',{headers:{Authorization:`Bearer ${token}`}});if(!response.ok)throw new Error('Audit export denied');const url=URL.createObjectURL(await response.blob());const link=document.createElement('a');link.href=url;link.download='growth-audit.ndjson';link.click();URL.revokeObjectURL(url);}catch(e){setError(e instanceof Error?e.message:'Export failed');}}
  return <div className="enterprise-workspace">
    <div className="section-heading"><div><h2>{connectorsOnly?'Enterprise connector registry':'Cross-domain orchestration'}</h2><p>Marketing, Advertising, Sales, Commerce and Service · deterministic execution authority</p></div><div className="heading-actions"><button className="button subtle" disabled={!token||busy} onClick={()=>void refresh()}><RefreshCw size={14}/>Refresh</button><button className="button primary" disabled={!token||busy} onClick={demo}><Play size={13}/>{busy?'Working…':'Run all domains'}</button></div></div>
    {error&&<div className="error" role="alert"><AlertCircle size={16}/>{error==='TENANT_NOT_PROVISIONED'?'Run the domain demo to initialize your synthetic workspace.':human(error)}</div>}
    {!token&&<div className="panel empty"><ShieldCheck size={26}/><h3>Connect your workspace to inspect enterprise workflows</h3></div>}
    {organization&&<div className="live-strip"><span><i/>{organization.tenantId}<span className="strip-divider"/>{organization.region}<span className="strip-divider"/>{organization.policyVersion}</span><small>{organization.killSwitch?'Execution paused':'Regional isolation enforced'}</small></div>}
    {connectorsOnly?<div className="connector-grid">{providers.map(p=><section className="panel connector-card" key={p.provider}><span className="domain-icon teal"><Link2 size={20}/></span><h2>{p.provider}</h2><span className="badge blue">{p.configuredProfiles?'Sandbox configured':'Pluggable · not connected'}</span><p>{p.activationRequirement??'Tenant-bound credentials, purpose-scoped context and typed operations. Production writes remain disabled.'}</p><div className="connector-fact"><ShieldCheck size={15}/> {p.configuredProfiles} configured profiles</div></section>)}<section className="panel connector-note"><h2>AWS deployment</h2><p>Regional worker queues and tenant data stay within their configured region. The AWS module and Helm chart define deployment boundaries; account credentials and approved sandbox mappings are supplied by the operator.</p></section></div>:<>
      <section className="metrics" aria-label="Enterprise workflow metrics">{[
        {name:'Regional workflows',value:Object.values(operations?.workflows??{}).reduce((a,b)=>a+b,0)},{name:'Governed actions',value:operations?.actions.ACCEPTED??0},
        {name:'Awaiting approval',value:operations?.workflows.APPROVAL_PENDING??0},
        {name:'Policy suppressions',value:operations?.actions.SUPPRESSED??0},
      ].map(m=><article className="metric" key={m.name}><div className="metric-top">{m.name}<GitBranch size={16}/></div><strong>{m.value}</strong><p>All purpose-authorized workflows</p></article>)}</section>
      <section className="panel"><div className="panel-heading"><div><h2>Growth workflow portfolio</h2><p>Typed plans, domain authority and action-level evidence</p></div><button className="button subtle" disabled={!organization} onClick={exportAudit}><Download size={13}/>Audit export</button></div><div className="heading-actions" style={{padding:'16px',flexWrap:'wrap'}}><label>Status <select aria-label="Workflow status" value={status} onChange={e=>setStatus(e.target.value)}><option value="">All statuses</option>{['RECEIVED','PLANNED','EXECUTING','APPROVAL_PENDING','COMPLETED','SUPPRESSED','HOLDOUT','CANCELLED','EXPIRED','FAILED_REVIEW','DRY_RUN'].map(value=><option key={value} value={value}>{human(value)}</option>)}</select></label><label>Customer reference <input aria-label="Customer reference filter" value={customer} maxLength={96} onChange={e=>setCustomer(e.target.value)} placeholder="Exact customer reference"/></label><button className="button subtle" onClick={()=>{setStatus('');setCustomer('');}}>Clear filters</button></div><div className="table-scroll"><table><thead><tr><th>SIGNAL / CUSTOMER</th><th>REGION</th><th>STATUS</th><th>DOMAIN ACTIONS</th><th><span className="sr-only">Inspect workflow</span></th></tr></thead><tbody>{workflows.map(w=><tr key={w.workflowId}><td><div className="journey-cell"><span className="journey-icon"><GitBranch size={16}/></span><div><strong>{human(w.signal)}</strong><small>{w.customerRef}</small></div></div></td><td>{w.region}</td><td><span className={`badge ${w.state==='COMPLETED'?'green':w.state==='SUPPRESSED'?'amber':'blue'}`}>{human(w.state)}</span></td><td>{w.actions.map(a=>a.domain).join(' · ')||'Planning'}</td><td><button className="icon-button" aria-label={`Inspect ${w.customerRef}`} onClick={()=>setSelected(w)}><ChevronRight size={18}/></button></td></tr>)}</tbody></table>{!workflows.length&&<div className="empty"><GitBranch size={28}/><h3>No cross-domain workflows yet</h3><p>Run all domains to exercise lead qualification, recovery, recommendations and approved audiences.</p></div>}</div>{cursor&&<div className="table-footer"><button className="button subtle" onClick={()=>void more()}>Load more workflows</button></div>}</section>
      {selected&&<section className="panel enterprise-detail" aria-label="Enterprise workflow details"><div className="panel-heading"><div><h2>{human(selected.signal)} · {selected.customerRef}</h2><p>{selected.region} · {selected.policyVersion}</p></div><button className="button subtle" onClick={()=>setSelected(null)}>Close details</button></div><div className="enterprise-detail-body"><p className="mono">Correlation: {selected.correlationId}</p><div className="agent-stages">{selected.decision?.agents.map(agent=><div className="proposal" key={agent.domain}><strong>{agent.domain}</strong><span><Check size={12}/> {agent.state.toLowerCase()}</span><small>{agent.dependencies.length?`After ${agent.dependencies.join(' & ')}`:'Context assessment'} · {agent.modelVersion}</small></div>)}</div><h3>Authorized actions</h3>{selected.actions.map(a=><article className="action-evidence" key={a.actionId}><div><strong>{a.domain}</strong><span className={`badge ${a.state==='ACCEPTED'?'green':a.state==='SUPPRESSED'?'amber':'blue'}`}>{human(a.state)}</span></div><p>{human(a.tool)}</p><small>{human(a.reasonCode??'pending')} · {a.attempts} attempts</small>{a.externalRef&&<code>{a.externalRef}</code>}</article>)}<div className="drawer-actions">{selected.state==='APPROVAL_PENDING'&&<button className="button primary" disabled={busy} onClick={()=>command('approve')}><ShieldCheck size={14}/>Approve bound plan & recheck</button>}{selected.state==='FAILED_REVIEW'&&<button className="button primary" disabled={busy} onClick={()=>command('replay')}>Reconcile & replay</button>}{!finished.has(selected.state)&&<button className="button subtle" disabled={busy} onClick={()=>command('cancel')}>Cancel workflow</button>}</div></div></section>}
    </>}
  </div>;
}
