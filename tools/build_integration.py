"""Build Postman and a ZIP from the verified Medical Devices specification."""
import json
from pathlib import Path
import zipfile
import yaml

ROOT = Path(__file__).resolve().parents[1] / "integration"
SPEC = yaml.safe_load((ROOT / "openapi.yaml").read_text())
BASE_PAYLOAD = SPEC["components"]["requestBodies"]["SearchBody"]["content"]["application/json"]["example"]


def script(phase, code):
    return {"listen": phase, "script": {"type": "text/javascript", "exec": code.strip().splitlines()}}


common = script("test", """
pm.test('HTTP 200', () => pm.response.to.have.status(200));
const jsonResponse = /json/i.test(pm.response.headers.get('Content-Type') || '');
pm.test('JSON, not HTML rejection', () => pm.expect(jsonResponse).to.equal(true));
if (jsonResponse) {
    const envelope = pm.response.json();
    pm.test('Application success', () => pm.expect(envelope.statusCode).to.equal(200));
    pm.test('returnObject present', () => pm.expect(envelope.returnObject).to.not.equal(null).and.not.equal(undefined));
}
""")
items = []
for index, (path, operations) in enumerate(SPEC["paths"].items(), 1):
    method, op = next(iter(operations.items()))
    prepare = "const p = " + json.dumps(BASE_PAYLOAD) + ";\n"
    if index == 1:
        prepare += """
pm.environment.unset('registration_number'); pm.environment.unset('selection_query');
if (!/^[0-9]+$/.test(String(pm.environment.get('page_number')))) throw new Error('page_number must be nonnegative');
if (!/^[1-9][0-9]*$/.test(String(pm.environment.get('page_size')))) throw new Error('page_size must be positive');
if (!['true','false'].includes(String(pm.environment.get('declaration_only')))) throw new Error('declaration_only must be true/false');
p.pageNumber = Number(pm.environment.get('page_number'));
p.maxResaults = Number(pm.environment.get('page_size'));
p.search = String(pm.environment.get('search_text') || '');
p.typePremission = pm.environment.get('declaration_only') === 'true';
"""
        test = """
if (pm.response.code === 200 && /json/i.test(pm.response.headers.get('Content-Type') || '')) {
    const e = pm.response.json(), d = e.returnObject;
    if (e.statusCode === 200 && d) {
        pm.test('Search count and list', () => { pm.expect(d.totalRows).to.be.a('number'); pm.expect(d.medicalAccessoriesList).to.be.an('array'); });
        if (Array.isArray(d.medicalAccessoriesList) && d.medicalAccessoriesList.length) {
            pm.environment.set('registration_number', String(d.medicalAccessoriesList[0].registrationNumber));
            pm.environment.set('selection_query', JSON.stringify([pm.environment.get('search_text'), pm.environment.get('declaration_only')]));
        }
    }
}
"""
    elif index == 2:
        prepare += """
const number = String(pm.environment.get('registration_number') || '');
if (!/^[0-9]+$/.test(number) || !Number.isSafeInteger(Number(number)) || Number(number) <= 0) throw new Error('Run 01 search first');
if (pm.environment.get('selection_query') !== JSON.stringify([pm.environment.get('search_text'), pm.environment.get('declaration_only')])) throw new Error('Filters changed; run search again');
p.registrationNumber = Number(number);
"""
        test = """
if (pm.response.code === 200 && /json/i.test(pm.response.headers.get('Content-Type') || '')) {
    const e = pm.response.json(), rows = e.returnObject && e.returnObject.medicalAccessoriesList;
    pm.test('Detail rows present (totalRows may be 0)', () => pm.expect(rows).to.be.an('array').that.is.not.empty);
    if (Array.isArray(rows)) pm.test('Registration identity matches', () => {
        for (const row of rows) pm.expect(String(row.registrationNumber)).to.equal(pm.environment.get('registration_number'));
    });
}
"""
    else:
        field, variable = {3: ("accessoryName", "accessory_filter"), 4: ("manufacter", "manufacturer_filter"),
                           5: ("registeredOwner", "owner_filter")}[index]
        prepare += f"p.{field} = String(pm.environment.get('{variable}') || '');\n"
        test = """
if (pm.response.code === 200 && /json/i.test(pm.response.headers.get('Content-Type') || '')) {
    const rows = pm.response.json().returnObject;
    pm.test('Filter options array', () => pm.expect(rows).to.be.an('array'));
    if (Array.isArray(rows)) pm.test('Option names and keys', () => {
        for (const row of rows) { pm.expect(row).to.have.property('name'); pm.expect(row).to.have.property('key'); }
    });
}
"""
    prepare += "\npm.variables.set('request_json', JSON.stringify(p));"
    items.append({"name": f"{index:02d} - {op['operationId']}",
        "request": {"method": method.upper(), "url": {"raw": "{{base_url}}" + path,
            "host": ["{{base_url}}"], "path": [path[1:]]},
            "header": [{"key": "Accept", "value": "application/json"}, {"key": "Content-Type", "value": "application/json"}],
            "body": {"mode": "raw", "raw": "{{request_json}}", "options": {"raw": {"language": "json"}}},
            "description": op.get("description", op["summary"])},
        "event": [script("prerequest", prepare), script("test", test)], "response": []})

collection = {"info": {"name": "MOH Medical Devices - Integration",
    "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    "description": "Consumer-maintained API requests, verified 2026-10-20. Import/select the environment, run 01 then 02; 03-05 are independent filter lookups. Every request is read-only POST. No authentication or browser cookies included. Keep TLS validation enabled and Runner delay >=2000ms. No bulk pagination or table writes are automated here."},
    "auth": {"type": "noauth"}, "event": [common], "item": items}
values = {"base_url": "https://registries.health.gov.il/api/MedicalDevices", "page_number": "0", "page_size": "20",
          "search_text": "", "declaration_only": "false", "registration_number": "", "selection_query": "",
          "accessory_filter": "Somnu", "manufacturer_filter": "DISCOVER", "owner_filter": "DISCOVER"}
environment = {"name": "MOH Medical Devices", "_postman_variable_scope": "environment",
    "values": [{"key": key, "value": value, "enabled": True, "type": "default"} for key, value in values.items()]}
for filename, value in [("medical-devices.postman_collection.json", collection),
                        ("medical-devices.postman_environment.json", environment)]:
    (ROOT / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
with zipfile.ZipFile(ROOT / "medical-devices-api.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for filename in ("medical-devices.postman_collection.json", "medical-devices.postman_environment.json", "openapi.yaml", "README.txt"):
        z.write(ROOT / filename, filename)
print("Built 5 Postman requests, environment, Swagger and API ZIP")
