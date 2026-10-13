"""U-P01原失败的独立实际Excel/HTML/PDF复测；不修改产品/夹具。"""
import argparse
from pathlib import Path
import os
from pypdf import PdfReader
from playwright.sync_api import sync_playwright
from tools.run_testbench import source_fingerprint,source_stability,write_report,exit_status
from .common import Recorder,service,dump,assert_excel
from .usability import fictional_plan,physical_snapshot,assert_seating_html,assert_seating_pdf


def run(directory):
    directory=Path(directory);rec=Recorder(directory);before=source_fingerprint()
    with sync_playwright() as pw:
        executable=Path(pw.chromium.executable_path)
        package=next((p for p in executable.parents if p.name.startswith('chromium-')),None)
        candidates=sorted(package.parent.glob('chromium_headless_shell-'+package.name.removeprefix('chromium-')+'/*/chrome-headless-shell*')) if package else []
        chosen=os.environ.get('EXAM_ROOM_TESTBENCH_PDF_BROWSER') or str(next((p for p in candidates if p.is_file()),executable))
        os.environ['EXAM_ROOM_BROWSER']=chosen
        browser=pw.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000})
        try:
            with service(directory/'完全虚构服务',fictional_plan(special=True,custom=True,locked=True)) as c:
                p=c.call('state')['plan'];coords=physical_snapshot(p);dump(directory/'虚构原始方案.json',p)
                p=c.call('seat_labels_apply',{'room_id':'r01','first':4,'second':2,'revision':p['revision']})['plan']
                assert physical_snapshot(p)==coords;dump(directory/'虚构交换后方案.json',p)
                def excel():
                    sections=list(c.call('state')['sections']);assert len(sections)==16
                    info=c.call('export',{'format':'xlsx','sections':sections,'draft':True});blob=c.download(info)
                    path=directory/'实际全部16类.xlsx';path.write_bytes(blob);assert_excel(blob,p,sections)
                    return dict(sections=16,all_identity_exam_labels_numbers_verified=True,path=str(path.resolve()))
                rec.run('MAT-excel','实际全部16类Excel独立核对',excel)
                for exam_id in ('e7-1','e7-2'):
                    target=directory/exam_id;target.mkdir(exist_ok=True)
                    def materials(exam_id=exam_id,target=target):
                        scope={'mode':'exam','exam_ids':[exam_id],'room_ids':['r01']};body={'sections':['seating'],'draft':True,'scope':scope}
                        html=c.download(c.call('export',{'format':'html',**body})).decode('utf-8')
                        html_path=target/'实际产品HTML.html';html_path.write_text(html,encoding='utf-8')
                        page.set_content(html);page.screenshot(path=str(target/'实际HTML.png'),full_page=True)
                        info=c.call('export',{'format':'pdf',**body});assert info['kind']=='pdf',info
                        pdf_path=target/'实际产品PDF.pdf';pdf_path.write_bytes(c.download(info));reader=PdfReader(pdf_path)
                        assert len(reader.pages)==info['page_count']
                        (target/'实际PDF文本.txt').write_text('\n'.join(p.extract_text(extraction_mode='layout') or '' for p in reader.pages),encoding='utf-8')
                        # 与首失败相同的固定/单科原断言，列和身份均独立读取。
                        html_checked=assert_seating_html(html,p,exam_id)
                        pdf_checked=assert_seating_pdf(reader,p,exam_id)
                        result=dict(html=html_checked,pdf=pdf_checked,page_count=len(reader.pages),html_path=str(html_path.resolve()),pdf_path=str(pdf_path.resolve()))
                        dump(target/'独立材料核对.json',result);return result
                    rec.run('MAT-'+exam_id,'实际固定/特殊单科物理列及身份',materials)
                page.goto('about:blank')
        finally:browser.close()
    after=source_fingerprint();cases=rec.cases+[source_stability(before,after)]
    data=dict(mode='1.1.0原材料独立复测',environment=dict(source_sha256_before=before,source_sha256_after=after,fictional=True,pdf_browser=chosen),
        cases=cases,limitations=['仅本机源码实际材料复测，不代表完整full/Windows/native/冻包/实机/系统打印。'])
    write_report(directory,data);code=exit_status(cases);dump(directory/'terminal.json',{'exit_code':code,'summary':data['summary'],'source_stable':before==after})
    print(str((directory/'report.html').resolve()),data['summary'],flush=True);return code


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,required=True)
    raise SystemExit(run(ap.parse_args().output))
