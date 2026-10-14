const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');
const target = path.join(root, '.env');
let content = fs.existsSync(target) ? fs.readFileSync(target, 'utf8') : fs.readFileSync(path.join(root, '.env.example'), 'utf8');
for (const [key, placeholder] of [['POSTGRES_PASSWORD', 'troque-por-uma-senha-forte'], ['BARBERFLOW_BOOTSTRAP_KEY', 'gere-uma-chave-aleatoria-longa']]) {
  const pattern = new RegExp(`^${key}=(.*)$`, 'm');
  const value = content.match(pattern)?.[1]?.trim();
  if (!value || value === placeholder) {
    const line = `${key}=${crypto.randomBytes(32).toString('hex')}`;
    content = pattern.test(content) ? content.replace(pattern, line) : content.trimEnd() + '\n' + line + '\n';
  }
}
fs.writeFileSync(target, content);
console.log('.env preparado. As credenciais existentes foram preservadas; consulte a chave de primeiro acesso nesse arquivo.');
