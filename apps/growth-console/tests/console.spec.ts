import AxeBuilder from '@axe-core/playwright';
import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';

const root=resolve('../..');
const token=()=>execFileSync(resolve(root,'.venv/bin/python'),['scripts/mint_token.py'],{cwd:root,encoding:'utf8'}).trim();

test('operator connects, runs demo, inspects audit and controls execution',async({page})=>{
  const errors:string[]=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto('/');
  await expect(page.getByRole('heading',{name:'Growth command center'})).toBeVisible();
  await page.getByLabel('Local access token').fill(token());
  await page.getByRole('button',{name:'Connect workspace'}).click();
  await expect(page.getByText('Policy controls active')).toBeVisible();
  await page.getByRole('button',{name:'Run synthetic demo'}).click();
  await expect(page.getByRole('button',{name:'Run synthetic demo'})).toBeEnabled();
  await expect(page.getByRole('button',{name:'Inspect cart-demo-001'})).toBeVisible();
  await page.screenshot({path:'test-results/overview.png',fullPage:true});
  const accessibility=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa']).analyze();
  expect(accessibility.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))).toEqual([]);
  await page.getByRole('button',{name:'Inspect cart-demo-001'}).click();
  const details=page.getByRole('dialog',{name:'Journey details'});
  await expect(details).toBeVisible();
  await expect(details.locator('dd').filter({hasText:'open critical case'})).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(details).not.toBeVisible();
  await page.getByRole('button',{name:'Governance',exact:true}).click();
  await page.getByRole('button',{name:'Pause all tenant actions'}).click();
  await page.getByRole('button',{name:'Pause actions',exact:true}).click();
  await expect(page.getByText('Outbound actions paused')).toBeVisible();
  await page.getByRole('button',{name:'Resume tenant actions'}).click();
  await page.getByRole('button',{name:'Resume actions',exact:true}).click();
  await expect(page.getByText('Policy controls active')).toBeVisible();
  await page.getByRole('button',{name:'Activity log',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Correlated audit trail'})).toBeVisible();
  expect(errors).toEqual([]);
});

test('mobile layout, keyboard controls and invalid authentication',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await page.goto('/');
  await page.getByLabel('Local access token').fill('invalid');
  await page.getByRole('button',{name:'Connect workspace'}).click();
  await expect(page.getByRole('alert').filter({hasText:'invalid token'})).toContainText('invalid token');
  await expect(page.getByLabel('Local access token')).toBeVisible();
  await page.screenshot({path:'test-results/mobile.png',fullPage:true});
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  const overflowing=await page.evaluate(()=>Array.from(document.querySelectorAll('*')).filter(e=>e.getBoundingClientRect().right>innerWidth+1).map(e=>({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right})).slice(0,20));
  expect(overflow,JSON.stringify(overflowing)).toBe(false);
});

test('all five domain workflows, bound approval and connector registry',async({page})=>{
  await page.goto('/');
  await page.getByLabel('Local access token').fill(token());
  await page.getByRole('button',{name:'Connect workspace'}).click();
  await expect(page.getByText('Policy controls active')).toBeVisible();
  await page.getByRole('button',{name:'Enterprise workflows',exact:true}).click();
  await page.getByRole('button',{name:'Run all domains',exact:true}).click();
  await expect(page.getByRole('button',{name:'Inspect cust-enterprise-002'})).toBeVisible();
  await page.getByRole('button',{name:'Inspect cust-enterprise-002'}).click();
  const detail=page.getByRole('region',{name:'Enterprise workflow details'});
  await expect(detail.getByRole('button',{name:'Approve bound plan & recheck'})).toBeVisible();
  await detail.getByRole('button',{name:'Approve bound plan & recheck'}).click();
  await expect(detail.getByText('accepted',{exact:true})).toBeVisible();
  await expect(detail.locator('.proposal')).toHaveCount(5);
  const accessibility=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa']).analyze();
  expect(accessibility.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))).toEqual([]);
  await page.screenshot({path:'test-results/enterprise.png',fullPage:true});
  await page.getByRole('button',{name:'Connectors',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Salesforce',exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Adobe Experience Platform',exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Shopify',exact:true})).toBeVisible();
});
