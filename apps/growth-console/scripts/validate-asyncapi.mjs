import {Parser,fromFile,DiagnosticSeverity} from '@asyncapi/parser';
for(const file of ['asyncapi.yaml','asyncapi-v2.yaml']) {
 const {document,diagnostics}=await fromFile(new Parser(),new URL('../../../contracts/'+file,import.meta.url).pathname).parse();
 const errors=diagnostics.filter(d=>d.severity===DiagnosticSeverity.Error);
 if(!document||errors.length){console.error(errors);process.exit(1);}
 console.log(file+' parsed and validated.');
}
