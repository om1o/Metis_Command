// Primitives.jsx — Button, Card, Chip, Input, Icon helpers

const Icon = ({ name, size = 18, ...rest }) => (
  <i data-lucide={name} style={{ width: size, height: size, display: 'inline-flex' }} {...rest}></i>
);

const Button = ({ variant = 'primary', size, leading, trailing, children, ...rest }) => {
  const cls = ['btn', `btn-${variant}`, size === 'sm' && 'btn-sm'].filter(Boolean).join(' ');
  return (
    <button className={cls} {...rest}>
      {leading && <Icon name={leading} size={16} />}
      {children}
      {trailing && <Icon name={trailing} size={16} />}
    </button>
  );
};

const IconButton = ({ name, size = 18, ...rest }) => (
  <button className="iconbtn" {...rest}><Icon name={name} size={size} /></button>
);

const Card = ({ hoverable, selectable, selected, className = '', children, ...rest }) => {
  const cls = ['card', hoverable && 'hoverable', selectable && 'selectable', selected && 'selected', className].filter(Boolean).join(' ');
  return <div className={cls} {...rest}>{children}</div>;
};

const Chip = ({ status = 'ready', children }) => (
  <span className={`chip chip-${status}`}><span className="chip-dot"></span>{children}</span>
);

const Input = (props) => <input className="input" {...props} />;

const Toggle = ({ on, onChange }) => (
  <button className={`toggle ${on ? 'on' : ''}`} onClick={() => onChange?.(!on)} aria-pressed={on}></button>
);

Object.assign(window, { Icon, Button, IconButton, Card, Chip, Input, Toggle });
