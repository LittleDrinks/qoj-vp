// Recover an already approved version after a downstream release failure.
// This module only performs GETs; a missing version is signed by web-ext.
import {createHash} from "node:crypto";
import {readFile, mkdir, writeFile, appendFile} from "node:fs/promises";
import {pathToFileURL} from "node:url";
import {resolve} from "node:path";
import {JwtApiAuth} from "web-ext/util/submit-addon";

const AMO = "https://addons.mozilla.org";
const DOWNLOAD_HOSTS = new Set(["addons.mozilla.org", "addons.cdn.mozilla.net"]);

function downloadUrl(raw) {
  const url = new URL(raw);
  if (url.protocol !== "https:" || !DOWNLOAD_HOSTS.has(url.hostname) || url.username || url.password || url.port) {
    throw new Error("AMO returned an unsupported download origin");
  }
  return url;
}

export async function recoverVersion({id, version, outputDir, getAuthHeader, fetchImpl = fetch}) {
  const endpoint = `${AMO}/api/v5/addons/addon/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}/`;
  const headers = async () => ({Authorization: await getAuthHeader(), "User-Agent": "qoj-vp-release/0.3"});
  const response = await fetchImpl(endpoint, {headers: await headers(), redirect: "error", signal: AbortSignal.timeout(60000)});
  if (response.status === 404) return {downloaded: false};
  if (!response.ok) throw new Error(`AMO version lookup failed (HTTP ${response.status})`);
  const record = await response.json();
  if (record.version !== version || record.channel !== "unlisted") throw new Error("AMO returned a different version or channel");
  if (record.file?.status !== "public") throw new Error("This AMO version already exists but is not approved; check its review status before retrying");
  const expectedHash = record.file.hash;
  if (!/^sha256:[0-9a-f]{64}$/.test(expectedHash || "")) throw new Error("AMO did not provide a SHA256 for this version");
  let target = downloadUrl(record.file.url);
  for (let attempt = 0; attempt < 5; attempt++) {
    const file = await fetchImpl(target.href, {redirect: "manual", signal: AbortSignal.timeout(60000),
      headers: target.origin === AMO ? await headers() : {"User-Agent": "qoj-vp-release/0.3"}});
    if ([301, 302, 303, 307, 308].includes(file.status)) {
      target = downloadUrl(new URL(file.headers.get("location"), target).href);
      continue;
    }
    if (!file.ok) throw new Error(`Signed XPI download failed (HTTP ${file.status})`);
    const bytes = Buffer.from(await file.arrayBuffer());
    if (bytes.length > 64 * 1024 * 1024 || "sha256:" + createHash("sha256").update(bytes).digest("hex") !== expectedHash) {
      throw new Error("Signed XPI does not match the AMO file hash");
    }
    await mkdir(outputDir, {recursive: true});
    const path = resolve(outputDir, `recovered-${version}.xpi`);
    await writeFile(path, bytes, {flag: "wx"});
    return {downloaded: true, path};
  }
  throw new Error("Too many signed XPI redirects");
}

async function main() {
  const manifest = JSON.parse(await readFile("src/firefox/manifest.json", "utf8"));
  const apiKey = process.env.WEB_EXT_API_KEY, apiSecret = process.env.WEB_EXT_API_SECRET;
  if (!apiKey || !apiSecret) throw new Error("Missing AMO credentials");
  const auth = new JwtApiAuth({apiKey, apiSecret});
  const result = await recoverVersion({id: manifest.browser_specific_settings.gecko.id,
    version: manifest.version, outputDir: "dist/amo", getAuthHeader: () => auth.getAuthHeader()});
  if (process.env.GITHUB_OUTPUT) await appendFile(process.env.GITHUB_OUTPUT, `downloaded=${result.downloaded}\n`);
  console.log(result.downloaded ? "Recovered the approved XPI from AMO; no new upload was sent" : "No existing AMO version; web-ext will request signing");
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(error => { console.error(error.message); process.exitCode = 1; });
}
