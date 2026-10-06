'use strict';
const assert=require('node:assert/strict'),ui=require('../titan/web/desktop_widgets.js');
assert.equal(ui.metrics({cpu_percent:0,memory_total:100,memory_used:10,memory_occupied:80}).ram,80);assert.equal(ui.metrics({cpu_percent:0}).cpu,0);
for(const value of [null,undefined,NaN,'50',-1,101])assert.equal(ui.metrics({cpu_percent:value}).cpu,null);
assert.equal(ui.metrics({memory_total:100,memory_occupied:101}).ram,null);
assert.deepEqual(ui.normalize({items:['ram','ram','bogus'],visible:false}),{items:['ram'],visible:false,collapsed:false});
assert.equal(ui.health(null),'Wird geladen');assert.equal(ui.health({service_details:{docker:{relevant:false,installed:false,active:false}}}),'Verbunden');
assert.equal(ui.health({service_details:{docker:{relevant:true,installed:false,active:false}}}),'Dienste prüfen');assert.equal(ui.health({telemetry_errors:{cpu:'offline'}}),'Messhinweise vorhanden');
console.log('Desktop widgets: occupied RAM, unavailable values, relevant service failures and saved selection passed.');
