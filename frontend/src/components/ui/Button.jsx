import { Link } from 'react-router-dom'
import { buttonClasses } from './buttonStyles'

/** Renders a <Link> when `to` is given, otherwise a <button>. */
export default function Button({ variant, size, className, to, type = 'button', ...props }) {
  const classes = buttonClasses({ variant, size, className })
  if (to) return <Link to={to} className={classes} {...props} />
  return <button type={type} className={classes} {...props} />
}
