// Browser-lane acceptance: send Browser.setDownloadBehavior for the context the PAGE lives in. browser.newPage() makes a
// NEW context, and Playwright gives it its own `allowAndName` behaviour (into its downloads folder); an override sent
// for the contexts listed before the page existed never reaches it. So the page's own session asks for its target's
// browserContextId, and the override is sent for exactly that id. Returns 1 when sent, 0 when the id is unknown.
async function overrideDownloads(cdp, pageSession, dir) {
  const { targetInfo } = await pageSession.send('Target.getTargetInfo');
  const id = targetInfo && targetInfo.browserContextId;
  if (!id) return 0;
  await cdp.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: dir, eventsEnabled: true, browserContextId: id });
  return 1;
}
module.exports = { overrideDownloads };
