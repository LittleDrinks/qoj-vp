// Bundle the pinned gitlinks directly. All consumers resolve ONE utils source.
import {build} from 'esbuild';
import less from 'less';
import {readFile, mkdir, copyFile, writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {execFileSync} from 'node:child_process';
const root = resolve(import.meta.dirname, '..');
const vendor = resolve(root, 'vendor');
const rendererPackage=JSON.parse(await readFile(resolve(vendor,'standard-ranklist-renderer-component/package.json'),'utf8'));
const aliases = {
  '@algoux/standard-ranklist-utils': resolve(vendor, 'standard-ranklist-utils/js/src/index.ts'),
  '@algoux/standard-ranklist-renderer-component-core': resolve(vendor, 'standard-ranklist-renderer-component/packages/core/src/index.ts'),
  '@algoux/standard-ranklist-renderer-component-styles': resolve(vendor, 'standard-ranklist-renderer-component/packages/styles/src/index.ts'),
};
const options = {bundle:true, platform:'browser', target:'firefox140', alias:aliases,
  define:{'process.env.NODE_ENV':'"production"',SRK_SUPPORTED_VERSIONS:JSON.stringify(rendererPackage.srkSupportedVersions)}, legalComments:'eof', minify:false,
  logOverride:{'ignored-bare-import':'silent'},
  plugins:[{name:'less',setup(b){b.onLoad({filter:/\.less$/},async args => ({
    contents:(await less.render(await readFile(args.path,'utf8'),{filename:args.path})).css,
    loader:'css', resolveDir:resolve(args.path,'..'),
  }));}}]};
await mkdir(resolve(root,'extension/board/generated'),{recursive:true});
await build({...options,entryPoints:['extension/board/engine.js'],outfile:'extension/board/generated/engine.js',format:'iife',globalName:'VpBoardEngine'});
await build({...options,entryPoints:['extension/board/view.jsx'],outfile:'extension/board/generated/view.js',format:'iife',globalName:'VpBoardView'});
const styleRoot=resolve(vendor,'standard-ranklist-renderer-component/packages/styles/src');
const css=await less.render(['Modal','ProgressBar','Ranklist'].map(name=>'@import "'+resolve(styleRoot,name+'.less')+'";').join('\n'));
await writeFile(resolve(root,'extension/board/generated/view.css'),css.css);
const revisions={};
for(const name of ['standard-ranklist-utils','standard-ranklist-renderer-component']) {
  const dir=resolve(vendor,name);
  try {
    const manifest=JSON.parse(await readFile(resolve(root,'SOURCE_MANIFEST.json'),'utf8'));
    revisions[name]=manifest.submodules['vendor/'+name];
  } catch(error) {
    if(error.code!=='ENOENT') throw error;
    revisions[name]=execFileSync('git',['-C',dir,'rev-parse','HEAD'],{encoding:'utf8'}).trim();
  }
  if(!/^[a-f0-9]{40}$/.test(revisions[name] || '')) throw new Error('Missing pinned revision for '+name);
  await copyFile(resolve(dir,'LICENSE'),resolve(root,'extension/board/generated',name+'.LICENSE'));
}
await writeFile(resolve(root,'extension/board/generated/upstream.json'),JSON.stringify(revisions,null,2)+'\n');
console.log('Board built from pinned submodules:',revisions);
