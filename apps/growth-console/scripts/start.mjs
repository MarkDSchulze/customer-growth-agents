import {cpSync} from 'node:fs';
const root=new URL('../.next/standalone/',import.meta.url);
cpSync(new URL('../.next/static',import.meta.url),new URL('.next/static',root),{recursive:true});
process.env.HOSTNAME='0.0.0.0';
await import(new URL('server.js',root).href);
