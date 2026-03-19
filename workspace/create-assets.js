const sharp = require('sharp');

async function createGradient(filename, color1, color2, angle = '135') {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080">
    <defs>
      <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" style="stop-color:${color1}"/>
        <stop offset="100%" style="stop-color:${color2}"/>
      </linearGradient>
    </defs>
    <rect width="100%" height="100%" fill="url(#g)"/>
  </svg>`;
  await sharp(Buffer.from(svg)).png().toFile(filename);
}

async function createCircleIcon(filename, color, size = 80) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}">
    <circle cx="${size/2}" cy="${size/2}" r="${size/2 - 4}" fill="${color}" opacity="0.15"/>
    <circle cx="${size/2}" cy="${size/2}" r="${size/2 - 4}" stroke="${color}" stroke-width="2" fill="none"/>
  </svg>`;
  await sharp(Buffer.from(svg)).png().toFile(filename);
}

async function createArrow(filename, color) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 40 40">
    <path d="M12 8 L28 20 L12 32" fill="none" stroke="${color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;
  await sharp(Buffer.from(svg)).png().toFile(filename);
}

async function createPhaseIcon(filename, number, bgColor, textColor) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">
    <rect width="64" height="64" rx="16" fill="${bgColor}"/>
    <text x="32" y="42" font-family="Arial" font-size="28" font-weight="bold" fill="${textColor}" text-anchor="middle">${number}</text>
  </svg>`;
  await sharp(Buffer.from(svg)).png().toFile(filename);
}

async function createCheckIcon(filename, color) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
    <circle cx="24" cy="24" r="20" fill="${color}" opacity="0.15"/>
    <path d="M14 24 L22 32 L34 16" fill="none" stroke="${color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;
  await sharp(Buffer.from(svg)).png().toFile(filename);
}

async function createWarningIcon(filename, color) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
    <circle cx="24" cy="24" r="20" fill="${color}" opacity="0.15"/>
    <path d="M24 14 L24 28" fill="none" stroke="${color}" stroke-width="3" stroke-linecap="round"/>
    <circle cx="24" cy="34" r="2" fill="${color}"/>
  </svg>`;
  await sharp(Buffer.from(svg)).png().toFile(filename);
}

async function createShieldIcon(filename, color) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
    <path d="M24 4 L40 12 L40 28 C40 36 32 44 24 44 C16 44 8 36 8 28 L8 12 Z" fill="${color}" opacity="0.15" stroke="${color}" stroke-width="2"/>
    <path d="M16 24 L22 30 L32 18" fill="none" stroke="${color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;
  await sharp(Buffer.from(svg)).png().toFile(filename);
}

async function main() {
  const dir = 'workspace/slides/';
  await createGradient(dir + 'bg-title.png', '#0D1B2A', '#1B3A5C');
  await createGradient(dir + 'bg-dark.png', '#0F1923', '#162A3E');
  await createGradient(dir + 'bg-light.png', '#F0F4F8', '#E2E8F0');
  await createPhaseIcon(dir + 'phase1.png', '1', '#00B4D8', '#FFFFFF');
  await createPhaseIcon(dir + 'phase2.png', '2', '#FF8C42', '#FFFFFF');
  await createPhaseIcon(dir + 'phase3.png', '3', '#06D6A0', '#FFFFFF');
  await createArrow(dir + 'arrow-right.png', '#00B4D8');
  await createCheckIcon(dir + 'check.png', '#06D6A0');
  await createWarningIcon(dir + 'warning.png', '#FF8C42');
  await createShieldIcon(dir + 'shield.png', '#00B4D8');
  console.log('Assets created.');
}

main().catch(console.error);
