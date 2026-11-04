const SRC = {
  waving: './mascot-waving.webp',
  reading: './mascot-reading.webp',
  clapping: './mascot-clapping.webp',
} as const;

export type MascotName = keyof typeof SRC;

interface MascotProps {
  name: MascotName;
  size?: 'large' | 'medium';
  animated?: boolean;
}

export function Mascot({ name, size = 'large', animated = false }: MascotProps) {
  return (
    <img
      className={`mascot mascot-${size}${animated ? ' mascot-bob' : ''}`}
      src={SRC[name]}
      alt=""
      width={320}
      height={320}
      draggable={false}
    />
  );
}
