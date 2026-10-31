import './profile-view.js?v=0.12.0';
import './profile-editor.js?v=0.12.0';

class LGPictureProfilesPanel extends HTMLElement {
  constructor() { super(); this.attachShadow({mode:'open'}); }
  set hass(value) { this._hass=value;this.setup(); }
  set panel(value) { this._panel=value;this.setup(); }
  setup() {
    if(!this._hass || !this._panel || this.editor)return;
    this.shadowRoot.innerHTML='<style>:host{display:flex;flex-direction:column;height:100dvh;background:#101a2b;color:#e9eef6}header{display:flex;align-items:center;padding:10px 18px;gap:16px;min-height:54px;font:16px system-ui;border-bottom:1px solid #34445b}button{font:inherit;background:transparent;color:inherit;border:1px solid #53637a;border-radius:8px;padding:7px 12px}lg-profile-editor{flex:1;min-height:0}</style><header><button aria-label="Open sidebar">☰</button><span></span></header><lg-profile-editor></lg-profile-editor>';
    this.shadowRoot.querySelector('header span').textContent=this._panel.config.title;
    this.shadowRoot.querySelector('button').onclick=()=>this.dispatchEvent(new CustomEvent('hass-toggle-menu',{bubbles:true,composed:true}));
    this.editor=this.shadowRoot.querySelector('lg-profile-editor');
    this.editor.configure({request:command=>this._hass.callWS({type:'lg_picture_profiles/editor',entry_id:this._panel.config.entry_id,command})});
  }
}
if(!customElements.get('lg-picture-profiles-panel'))customElements.define('lg-picture-profiles-panel',LGPictureProfilesPanel);
