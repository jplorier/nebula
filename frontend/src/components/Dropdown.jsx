import Button from './Button'
import styled from 'styled-components'

const DropdownContainer = styled.div`
  position: relative;
  display: inline-block;

  .dropdown-content {
    display: none;
    position: absolute;
    background-color: var(--color-surface-04);
    min-width: 100px;
    box-shadow: 0px 8px 16px 0px rgba(0, 0, 0, 0.2);
    z-index: 1;

    button {
      background: none;
      border: none;
      width: 100%;
      justify-content: flex-start;
      border-radius: 0;
      padding: 25px 10px;

      &:hover {
        background-color: var(--color-surface-03);
      }

      &:active,
      &:focus {
        outline: none !important;
      }

      &:disabled {
        color: var(--color-text-dim);
      }
    }
  }

  > button {
    // background: none;
    // border: none;
    // border-radius: 0;
    padding: 0 8px;
    justify-content: space-between;

    &:active,
    &:focus {
      outline: none !important;
    }
  }

  &:not(.disabled):hover .dropdown-content {
    display: block;
  }
`

const Dropdown = ({
  options,
  label = null,
  icon = 'expand_more',
  align = 'left',
  buttonStyle = {},
  contentStyle = {},
  value = null,
  disabled = false,
}) => {
  if (align === 'right') contentStyle['right'] = 0

  return (
    <DropdownContainer className={disabled ? 'disabled' : ''}>
      <Button
        className="dropbtn"
        style={buttonStyle}
        icon={icon}
        label={label}
        iconOnRight={true}
        disabled={disabled}
      />
      <div className="dropdown-content" style={contentStyle}>
        {options &&
          options.map((option, idx) => (
            <Button
              key={idx}
              {...option}
              disabled={option.disabled || value === option.value}
            />
          ))}
      </div>
    </DropdownContainer>
  )
}

export default Dropdown
