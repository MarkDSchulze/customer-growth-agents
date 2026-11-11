import {Parser,fromFile,DiagnosticSeverity} from '@asyncapi/parser';
const {document,diagnostics}=await fromFile(new Parser(),new URL('../../../contracts/asyncapi.yaml',import.meta.url).pathname).parse();
const errors=diagnostics.filter(d=>d.severity===DiagnosticSeverity.Error);
if(!document||errors.length){console.error(errors);process.exit(1);}
console.log('AsyncAPI 3.0 parsed and validated.');
