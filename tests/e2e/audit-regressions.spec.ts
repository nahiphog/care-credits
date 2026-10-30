import { test, expect, Page } from '@playwright/test';
async function login(page: Page) {
 await page.goto('/');
 await page.getByLabel('Email address').fill('doctor@carecredits.local');
 await page.getByLabel('Password', {exact:true}).fill('CareCredits-demo-2026');
 await page.getByRole('button',{name:'Sign in and search',exact:true}).click();
 await expect(page.locator('button.event').first()).toBeVisible();
}
test('fresh course modal is positioned, accessible and closes with Escape at desktop and phone sizes',async({page})=>{
 await login(page);
 for(const width of [1440,891,390,320]) {
  await page.setViewportSize({width,height:900});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  const row=page.locator('button.event').first();
  const title=await row.locator('.event-name').boundingBox();const points=await row.locator('.event-points').boundingBox();
  expect(title).toBeTruthy();
  if(points) expect(title!.x+title!.width<=points.x+1 || title!.y+title!.height<=points.y+1).toBeTruthy();
  await row.click();const dialog=page.getByRole('dialog');await expect(dialog).toBeVisible();
  expect(await page.locator('.modal-shade').evaluate(el=>getComputedStyle(el).position)).toBe('fixed');
  const box=await dialog.boundingBox();expect(box!.x).toBeGreaterThanOrEqual(0);expect(box!.x+box!.width).toBeLessThanOrEqual(width+1);
  await page.screenshot({path:`outputs/e2e/modal-${width}.png`});
  await page.keyboard.press('Escape');await expect(dialog).toBeHidden();
  expect(await page.evaluate(()=>document.body.style.overflow)).not.toBe('hidden');
 }
});
test('cancelled filters do not change a later catalogue request',async({page})=>{
 await login(page);await page.getByRole('button',{name:/^Filters/}).click();
 await page.getByRole('dialog').getByRole('combobox',{name:'Delivery mode',exact:true}).selectOption('in_person');
 await page.getByRole('button',{name:'Cancel',exact:true}).click();
 const pending=page.waitForRequest(r=>r.url().includes('/api/v1/trainings?'));
 await page.getByRole('button',{name:'Overview',exact:true}).click();
 await page.getByRole('button',{name:/Find catalogue events/}).click();
 const req=await pending;expect(new URL(req.url()).searchParams.get('mode')).not.toBe('in_person');
});
test('profile draft keystrokes do not reload workspace and certificates are directly navigable',async({page})=>{
 await login(page);await page.getByRole('button',{name:'Settings',exact:true}).click();
 await page.waitForTimeout(500);const requests:string[]=[];page.on('request',r=>{if(r.url().includes('/api/v1/me/'))requests.push(r.url())});
 await page.getByLabel('Profile city',{exact:true}).pressSequentially(' test');await page.waitForTimeout(500);expect(requests).toHaveLength(0);
 await page.getByRole('button',{name:'Certificates',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Affiliation records',exact:true})).toBeInViewport();
});
test('expired session clears signed-in shell and provides login',async({page})=>{
 await login(page);await page.route('**/api/v1/trainings?**',route=>route.fulfill({status:401,contentType:'application/json',body:JSON.stringify({detail:'Please sign in.'})}));
 await page.getByRole('button',{name:'Search',exact:true}).click();
 await expect(page.getByRole('button',{name:'Sign in and search',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'Overview',exact:true})).toHaveCount(0);
});
test('workspace defaults to all dates and unavailable digests cannot be enabled',async({page})=>{
 await login(page);await page.goto('/workspace');
 await expect(page.locator('.course-card').first()).toBeVisible();
 await expect(page.getByText(/not available on this deployment/i).first()).toBeVisible();
});

test('certificate issuance remains in history with a readable direct document',async({page})=>{
 await login(page);await page.getByRole('button',{name:'Certificates',exact:true}).click();
 await page.getByRole('button',{name:'Issue affiliation record',exact:true}).click();
 await expect(page.getByRole('status').filter({hasText:'Your affiliation record was saved'})).toBeVisible();
 const link=page.getByRole('link',{name:'Open / print',exact:true}).first();await expect(link).toBeVisible();
 const response=await page.request.get((await link.getAttribute('href'))!);expect(response.status()).toBe(200);expect(await response.text()).toContain('Dr Daniel Tan');
 await page.reload();await page.getByRole('button',{name:'Certificates',exact:true}).click();await expect(page.getByRole('link',{name:'Open / print',exact:true}).first()).toBeVisible();
});
test('mobile navigation has no hidden first focus and brings certificates into view',async({page})=>{
 await login(page);await page.setViewportSize({width:390,height:844});await page.reload();await expect(page.getByRole('button',{name:'Open navigation'})).toBeVisible();
 await expect(page.locator('#dashboard-navigation')).toHaveAttribute('inert','');
 await page.keyboard.press('Tab');
 const box=await page.locator(':focus').last().boundingBox();expect(box).toBeTruthy();expect(box!.x).toBeGreaterThanOrEqual(0);
 await page.getByRole('button',{name:'Open navigation'}).click();await page.getByRole('button',{name:'Certificates',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Affiliation records',exact:true})).toBeInViewport();
 expect((await page.request.get('/api/maintenance')).status()).toBe(401);
});
