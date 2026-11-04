import React from 'react';
import {createRoot} from 'react-dom/client';
import {Ranklist} from '../../../vendor/standard-ranklist-renderer-component/packages/react/src/main.ts';

const roots=new WeakMap();
export function render(element,snapshot) {
  let root=roots.get(element);
  if(!root){root=createRoot(element);roots.set(element,root);}
  root.render(<Ranklist data={snapshot.ranklist} rowStriped rowBordered columnBordered
    enableCCPC26 showProblemStatisticsFooter statusCellPreset="compact" languages={['zh-CN','en']}/>);
}

export function clear(element) {
  const root=roots.get(element);
  if(root){root.unmount();roots.delete(element);}
}
